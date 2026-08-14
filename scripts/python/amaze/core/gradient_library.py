"""
Models for the Gradients ("Colors") section.

Like the Cop and Code sections, a material-style library over its own
gradients.json - `GradientLibrary` subclasses the material machinery,
so records, categories, favourites, tile icons, search, deletion, the
refused-save contracts and the connector's guards all come from the
proven shared code paths. What differs:

- **A palette's payload is INLINE** - its `colors` list and full
  `ramp` (basis/key/value) ride on the record, so gradients.json is
  self-contained and there are no `<id>.mat`/thumbnail files.
- **Thumbnails are PAINTED**, not rendered - stacked bands for a
  stepped palette, a left-to-right gradient for a smooth ramp - via
  the unified engine's PAINT path, content-addressed so an edit mints
  a fresh preview.
- **The kind field reads `Gradient`** uniformly; which curated set or
  palette size an entry belongs to is category information.

The curated palettes are just prefilled colours, not read-only -
SEEDED once into the user gradients (see `seed_curated_palettes`),
from the JSON defs in res/def/ listed in CURATED_SETS: Sanzo Wada's
"A Dictionary of Color Combinations" (348 combinations; data
github.com/dblodorn/sanzo-wada, MIT, source work public domain), plus
artist sets from colour theory - Paul Klee (palette sampled from
"Farbtafel qu 1", 1930), Josef Albers (Homage to the Square /
Interaction of Color), Johannes Itten (twelve-part Farbkreis). After
seeding they are ordinary gradients: moveable, editable, deletable,
their colour-theory notes on their Comments pages. Each JSON documents
its own sources in a "source" field.
"""

import json
import os

import hou
from PySide6 import QtCore, QtGui

from amaze.core import category, grid_proxy
from amaze.core import database
from amaze.core import debug
from amaze.core import library
from amaze.core import locations
from amaze.core import material
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


# The curated (read-only) sets, in display order. Everything downstream
# reads ordinary user gradients, so adding a set here (plus its JSON in
# res/def/) is the whole job. "label" feeds the seeded category names
# ("Wada 5 Colors", ...).
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


def _row_categories(entry) -> list:
    """The categories one palette VIEW is filed under, as a list.

    The one reader the proxy shares with the section verbs. Tolerates
    the comma-string form for the reason `Categories._category_count`
    does - a hand-edited file, and an older build's row arriving
    through the peer merge.
    """
    cats = (entry or {}).get("categories", [])
    if isinstance(cats, str):
        cats = cats.split(",")
    if not isinstance(cats, list):
        return []
    return [c.strip() for c in cats if isinstance(c, str) and c.strip()]


class GradientCategories(category.Categories):
    """The Colors section's category sidebar - same model, own database.

    Three lines, like `CopCategories` and `CodeCategories`, plus the one
    thing this section genuinely asks that they do not: the proxy is
    driven by a (kind, value) pair rather than by a category name.

    It was a standalone list model until 2026-08-12, reading its rows
    through the library instead of the connector's document, and that
    second implementation is what let a peer's category be erased -
    the shared model holds a live alias, so what a merge adopts is
    already in the list the section writes.
    """

    DB_FILENAME = "gradients.json"

    def filter_for_row(self, row: int):
        """(kind, value) for the proxy: ("all", None) or
        ("category", name).

        DERIVED from the shared model's own rows rather than kept in a
        parallel list: row 0 is the `_All` marker and the rest are
        names, which is the order `Categories` already guarantees.
        `sections.py` reads this for both `select_category` and
        `sidebar_key`, so it stays the section's one reader of what a
        row MEANS.
        """
        if 0 <= row < len(self._categories):
            name = self._categories[row]
            if isinstance(name, str) and not name.startswith("_"):
                return ("category", name)
        return ("all", None)


class GradientLibrary(library.MaterialLibrary):
    """The Colors section's asset model - material machinery over
    gradients.json, with the palette payload inline and a painted
    preview."""

    NOTES_SECTION = "gradient"

    DB_FILENAME = "gradients.json"

    #: A palette lives INLINE in gradients.json, so a refused list
    #: write leaves nothing on disk to recover - the same answer the
    #: Code section gives for its snippets.
    CONTENT_SURVIVES_A_REFUSED_INDEX_WRITE = False

    COLUMN_ROLES = {
        "name": QtCore.Qt.ItemDataRole.DisplayRole,
        "type": "RendererLabelRole",
        "category": "CategoryLabelRole",
        "favorite": "FavoriteRole",
        "comments": "NotesRole",
    }

    #: List mode's Category column: the palette's category by NAME,
    #: "Uncategorized" for none. The family's CategoryRole answers a
    #: LIST for the proxy; this is the display string. Past the
    #: family's last number (+11); test_role_numbers holds the gap.
    CategoryLabelRole = QtCore.Qt.ItemDataRole.UserRole + 13

    def __init__(self, parent=None, preferences=None) -> None:
        super().__init__(parent, preferences=preferences)
        self._persist_minted_ids_once()
        self._sweep_notes_to_store_once()

    @staticmethod
    def _asset_from_row(row: dict):
        """A palette rides as a `Material` - `colors` and `ramp` in its
        carried-through keys - with two honesty rules of its own.

        `uid` was the pre-connector spelling of the identity; mapping
        it onto `id` keeps notes and tile icons keyed by the same
        value. And a stored row WITHOUT a date keeps an empty one:
        `Material` mints today's date for a blank, which is right for
        an asset being born and fabricated history for 388 palettes
        that simply predate the field.
        """
        row = dict(row)
        legacy = str(row.get("uid") or "")
        if legacy and not str(row.get("id") or ""):
            row["id"] = legacy
        mat = material.Material.from_dict(row)
        if not str(row.get("date") or ""):
            mat._date = ""
        return mat

    @property
    def _load_failed(self) -> bool:
        """Whether the connector is refusing to write this file. Read
        through to the connector's own latch - one answer to whether
        this file may be written."""
        if self.preferences is None:
            return False
        return bool(getattr(
            database.DatabaseConnector(self.DB_FILENAME),
            "_write_blocked", False))

    def switch_model_data(self) -> None:
        super().switch_model_data()
        self._persist_minted_ids_once()
        self._sweep_notes_to_store_once()

    # ------------------------------------------------------------------
    # The once-per-library sweeps.

    def _persist_minted_ids_once(self) -> None:
        """Identity from birth: `Material` mints an id for a row that
        arrived without one, and this writes the mint back so it IS the
        row's identity rather than a value that changes every launch -
        notes and tile icons are keyed by it.

        Stamped INTO the connector's own row, in place, before the
        save: the connector unions by id, so a save alone lands the
        minted row BESIDE the id-less original instead of replacing
        it - measured as a duplicate palette per launch."""
        raw = [row for row in (self._data.get("assets") or [])
               if isinstance(row, dict)]
        minted = 0
        for row, asset in zip(raw, self._assets):
            if not str(row.get("id") or row.get("uid") or ""):
                row["id"] = asset.mat_id
                minted += 1
        if minted and self.save():
            debug.event("gradients", "ids minted and persisted",
                        count=minted)

    def _sweep_notes_to_store_once(self) -> None:
        """The entry-level `note` text moved to the Notes store
        (2026-08-01): a gradient's free text belongs on its Comments
        page. Any row still carrying one - an old library, or a fresh
        curated seed - has it appended to its page here and the field
        consumed. Collected and written ONCE (per-entry writes rotated
        a snapshot each, 39 times); a note the store cannot take stays
        on the row and is retried next load - moved, never dropped."""
        from amaze.core import notes
        moved = cleared = 0
        pages = {}
        carriers = {}
        for asset in self._assets:
            extra = getattr(asset, "_extra", None)
            if not isinstance(extra, dict) or "note" not in extra:
                continue
            text = str(extra.get("note", "") or "").strip()
            if not text:
                del extra["note"]
                cleared += 1
                continue
            key = notes.note_key(self.NOTES_SECTION, asset.mat_id)
            page = notes.note_for(self.preferences, key)
            items = list(pages.get(key, page.get("items", [])))
            items.append({"t": "text", "text": text})
            pages[key] = items
            carriers.setdefault(key, []).append(extra)
        if pages and notes.set_notes(self.preferences, pages):
            for extras in carriers.values():
                for extra in extras:
                    extra.pop("note", None)
                    moved += 1
        if moved or cleared:
            self.save()
            debug.event("gradients", "notes swept to the notes store",
                        moved=moved, cleared=cleared)

    # ------------------------------------------------------------------
    # The curated seed.

    #: bump when the seed contents change, so a new set re-seeds
    _SEED_MARKER = ".amaze_gradient_seed_v1"
    #: Pre-rename marker; renamed on sight so an old library does not
    #: re-seed the curated gradients and duplicate them.
    _SEED_MARKER_LEGACY = ".assetlib_gradient_seed_v1"

    def seed_curated_palettes(self, category_model) -> None:
        """First run per library: every curated combination becomes a
        normal user gradient (stepped ramp, its set+size as the
        category, its colour-theory note on its Comments page). Called
        from the panel beside the Code section's snippet seed, with
        the categories registered through `check_add_category` so the
        sidebar hears its own insert signals. Guarded by a marker file;
        best-effort - never blocks panel startup."""
        try:
            lib_dir = self.preferences.dir
            if not lib_dir:
                return
            if self._load_failed:
                # A refused file must not earn a PERMANENT marker for a
                # save that never happened.
                return
            marker = os.path.join(lib_dir, self._SEED_MARKER)
            hostos.migrate_legacy_file(
                lib_dir, self._SEED_MARKER_LEGACY, self._SEED_MARKER)
            if os.path.exists(marker):
                return
            seeded = 0
            categories = []
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
                        curated["label"], n, "" if n == 1 else "s")
                    if cat_name not in categories:
                        categories.append(cat_name)
                    name = (combo.get("name")
                            or "Combination %s" % combo.get("id"))
                    mat = self._asset_from_row({
                        "name": name,
                        "categories": [cat_name],
                        "colors": colors,
                        "ramp": _palette_ramp_data(colors),
                        "note": combo.get("note", ""),
                    })
                    row = len(self._assets)
                    self.beginInsertRows(QtCore.QModelIndex(), row, row)
                    try:
                        self._assets.append(mat)
                    finally:
                        self.endInsertRows()
                    seeded += 1
            # Def files unreachable this run (AMAZE not set yet): leave
            # the marker off and retry next launch rather than
            # permanently blocking the seed.
            if not seeded:
                return
            self.rebuild_thumbs()
            # The marker is PERMANENT and gradients.json's only trace,
            # so it must not be minted for a save that never landed -
            # save() reports refusals by returning False, and the
            # exists() gate below cannot see them.
            if not self.save():
                debug.event("gradient", "curated seed not marked - the "
                            "save did not reach disk")
                return
            for cat_name in categories:
                category_model.check_add_category(cat_name)
        except Exception as exc:                        # noqa: BLE001
            debug.event("gradient", "curated palette seed failed",
                        error=str(exc))
            return
        # NOT written when the database is not on disk: the marker is
        # the absent-database guard's evidence that this list existed,
        # and database.save() reports an OSError instead of raising -
        # so a save held off by a full disk lands here looking
        # successful, and a marker with no database behind it refuses
        # gradients.json on every future launch.
        if not os.path.exists(os.path.join(lib_dir, self.DB_FILENAME)):
            debug.event("gradient", "seed marker withheld - the "
                        "database is not on disk", file=lib_dir)
            return
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
            # A RECORD, not a guard - the comment above says what
            # actually happens next launch, and hand-deleting 348
            # duplicated palettes is not a next step that works.
            self._seed_marker_failed = True
            return
        # The seeded notes move to their Comments pages in the SAME
        # session, not on the next launch's sweep.
        self._sweep_notes_to_store_once()

    # ------------------------------------------------------------------
    # The palette payload, read off the record.

    @staticmethod
    def _colors_of(asset) -> list:
        """The palette's colour dicts - carried through on the record
        beside the fields the family knows."""
        extra = getattr(asset, "_extra", None) or {}
        colors = extra.get("colors")
        return colors if isinstance(colors, list) else []

    @staticmethod
    def _ramp_of(asset) -> dict:
        extra = getattr(asset, "_extra", None) or {}
        ramp = extra.get("ramp")
        return ramp if isinstance(ramp, dict) else {}

    def entry(self, row: int) -> dict | None:
        """READ-ONLY view of one palette - name, categories, colors,
        ramp - for the section's ramp verbs and the proxy's colour-name
        search. A copy on purpose: edits go through the record API, not
        through this dict."""
        if not 0 <= row < len(self._assets):
            return None
        asset = self._assets[row]
        return {
            "name": asset.name,
            "categories": list(asset.categories),
            "colors": self._colors_of(asset),
            "ramp": self._ramp_of(asset),
        }

    def is_favorite(self, row: int) -> bool:
        """The star, from the library store under its owner - the same
        door the inherited FavoriteRole answers; this int-row spelling
        is what the Colors proxy reads."""
        if not 0 <= row < len(self._assets):
            return False
        return locations.is_favourite(
            self.preferences, self._assets[row].mat_id)

    def toggle_favorite(self, row: int) -> None:
        self.toggle_fav(self.index(row, 0))

    def note_uid(self, row: int) -> str:
        """A palette's identity - its record id, same key its Comments
        page and tile icon use."""
        if not 0 <= row < len(self._assets):
            return ""
        return str(self._assets[row].mat_id)

    # ------------------------------------------------------------------
    # The category list, through the connector's document. Temporary
    # spellings: the section drives these until it rebases onto
    # `AssetSection`, whose verbs use the sidebar model directly.

    def user_categories(self) -> list:
        """The categories the save dialog lists, without the `_All`
        marker - the view edge filters; what is stored keeps it."""
        return [name for name in self._data.get("categories", [])
                if isinstance(name, str) and name != "_All"]

    def add_user_category(self, name: str) -> None:
        name = (name or "").strip()
        cats = self._data.setdefault("categories", [])
        if name and name not in cats:
            cats.append(name)
            self.save()

    def count_in_category(self, name: str) -> int:
        return sum(1 for a in self._assets if name in a.categories)

    def set_user_category(self, rows: list, category_name: str) -> int:
        """Move the given rows' palettes to a category (dragged onto a
        sidebar row, or the Move-to menu). Returns how many moved."""
        category_name = (category_name or "").strip()
        if not category_name:
            return 0
        cats = self._data.setdefault("categories", [])
        if category_name not in cats:
            cats.append(category_name)
        moved = 0
        for row in rows:
            if not 0 <= row < len(self._assets):
                continue
            asset = self._assets[row]
            if asset.categories != [category_name]:
                asset.categories = category_name
                moved += 1
        if moved:
            self.save()
            for row in rows:
                self.row_changed(row)
        return moved

    def rename_user_category(self, old: str, new: str) -> bool:
        """Rename a palette category, carrying its palettes AND its
        colour across - the same contract the asset sections have."""
        old = str(old or "").strip()
        new = str(new or "").strip()
        if not old or not new or old == new:
            return False
        cats = self._data.setdefault("categories", [])
        if old in cats:
            # IN PLACE: the list is the connector's own document.
            cats[cats.index(old)] = new
        elif new not in cats:
            cats.append(new)
        table = self._data.get("category_colors")
        if isinstance(table, dict):
            colour = table.pop(old, "")
            if colour:
                table[new] = colour
        self.rename_category(old, new)
        if not self.save():
            return False
        self._repaint_rows()
        return True

    def remove_user_category(self, name: str) -> None:
        """Drops the category itself; its palettes are kept, just
        uncategorized (still listed under All)."""
        cats = self._data.setdefault("categories", [])
        if name in cats:
            cats.remove(name)
        table = self._data.get("category_colors")
        if isinstance(table, dict):
            # A removed category takes its colour with it - an orphan
            # key would silently reattach if the name ever came back.
            table.pop(name, None)
        self.remove_category(name)
        self.save()
        self._repaint_rows()

    def _repaint_rows(self) -> None:
        """Category edits change subtitles and the Category column on
        every affected row; one bounded emit covers them."""
        if self.rowCount():
            self.dataChanged.emit(
                self.index(0, 0), self.index(self.rowCount() - 1, 0),
                [self.CategoryRole, self.CategoryLabelRole,
                 self.CategoryColorRole])

    # ------------------------------------------------------------------
    # Add and delete - the record API over the shared save contracts.

    def add_user_gradient(self, name: str, category_name: str,
                          ramp_data: dict) -> None:
        """Registers a saved ramp. The colour list is derived from the
        ramp values so search/swatches/subtitles work identically to
        the seeded entries (hex stands in for a colour name)."""
        colors = []
        for value in ramp_data.get("values", []):
            hex_color = "#%02x%02x%02x" % tuple(
                max(0, min(255, round(c * 255))) for c in value[:3]
            )
            colors.append({"name": hex_color, "hex": hex_color})
        category_name = (category_name or "").strip()
        cats = self._data.setdefault("categories", [])
        if category_name and category_name not in cats:
            cats.append(category_name)
        mat = material.Material()
        mat.set_data((name or "Gradient").strip() or "Gradient",
                     category_name, "", False, "")
        mat._extra = {"colors": colors, "ramp": ramp_data}
        # At the TOP: the Colors grid shows source order (no sort is
        # ever applied to its proxy), and the newest palette belongs
        # where the eye is.
        self.beginInsertRows(QtCore.QModelIndex(), 0, 0)
        try:
            self._assets.insert(0, mat)
        finally:
            self.endInsertRows()
        self.rebuild_thumbs()
        if not self.save():
            # NOTHING REACHED DISK, so nothing stays on screen: a
            # palette left in the grid by a refused save is gone at the
            # next launch with nothing ever said.
            self.beginRemoveRows(QtCore.QModelIndex(), 0, 0)
            try:
                del self._assets[0]
            finally:
                self.endRemoveRows()
            self.rebuild_thumbs()
            debug.alert(
                'Amaze could not save "%s".\n\n'
                "Nothing else has been lost - your other colors are "
                "exactly as they were.\n\n"
                "Close any other Amaze panel, or restart Houdini, then "
                "try again." % (name or "this palette"),
                key="colors-not-saved")
            return
        self.row_changed(0)

    def remove_user_gradient(self, row: int) -> None:
        """Delete a palette, honouring the connector's answer.

        The shared shape of `remove_asset` without its file pass - a
        palette owns nothing on disk beyond its row. `removeRow` says
        the delete out loud (the connector unions rows, so an unspoken
        delete comes straight back); a refusal puts the row back, in
        the model AND in the connector's document, because `set()` has
        already consumed the mark by then.
        """
        if not 0 <= row < len(self._assets):
            return
        asset = self._assets[row]
        if not self.removeRow(row):
            return
        if not self.save():
            self.beginInsertRows(QtCore.QModelIndex(), row, row)
            try:
                self._assets.insert(row, asset)
            finally:
                self.endInsertRows()
            self.rebuild_thumbs()
            try:
                connector = database.DatabaseConnector(self.DB_FILENAME)
                connector.unforget(asset.mat_id)
                connector.set({"assets": [asset.get_as_dict()]})
            except (AttributeError, TypeError) as exc:
                debug.event("gradient", "could not take back a row "
                            "removal", error=str(exc))
            debug.alert(
                '"%s" was not deleted, because Amaze could not update '
                "your colors.\n\n"
                "Nothing was removed - the palette is exactly as it "
                "was.\n\n"
                "Close any other Amaze panel, or restart Houdini, then "
                "try again." % (asset.name or "That palette"),
                key="colors-delete-refused")

    def cleanup_db(self, show_dialog: bool = True) -> int:
        """A palette lives inline - there are no payload files - so the
        inherited missing-file and lonely-file passes would classify
        every palette as an orphan. Reduced to a state flush, the Code
        section's answer."""
        self.save()
        self.last_cleanup_summary = [
            "Colors: nothing to clean (palettes are stored inline)."
        ]
        return 0

    # ------------------------------------------------------------------
    # The painted preview.

    def set_tile_icon(self, index, spec, save: bool = True) -> bool:
        """Give one palette a tile icon, or clear it with an empty
        spec. NO PNG is written, unlike the file-backed sections: the
        icon is composed in memory by the paint path, which is what the
        swatch already does, so there is nothing on disk to clean up."""
        row = index.row() if hasattr(index, "row") else int(index)
        if not 0 <= row < len(self._assets):
            return False
        spec = tile_icons.normalise(spec)
        stored = tile_icons.set_override(
            self.preferences, str(self._assets[row].mat_id), spec)
        if save:
            self.save()
        self.row_changed(row, [QtCore.Qt.ItemDataRole.DecorationRole])
        return bool(stored)

    @staticmethod
    def _is_banded(colors: list, ramp: dict) -> bool:
        """A palette / stepped ramp paints as bands; a smooth ramp as a
        gradient. True when every basis is Constant (or there is no
        ramp yet)."""
        bases = ramp.get("bases") or []
        return bool(colors) and (
            not bases or all(b == "Constant" for b in bases)
        )

    def _swatch_key(self, row: int):
        """Content-addressed (hexes, ramp bases, stop positions, the
        icon) - renames cannot stale it, edits naturally mint a new key
        and the old image ages out of the shared LRU."""
        asset = self._assets[row]
        colors = self._colors_of(asset)
        ramp = self._ramp_of(asset)
        hexes = tuple(c.get("hex") for c in colors if isinstance(c, dict))
        bases = tuple(ramp.get("bases") or ())
        # The stop POSITIONS too: two palettes with the same colours in
        # different places paint differently and must not share a slot.
        stops = tuple(round(float(k), 6) for k in (ramp.get("keys") or ())
                      if isinstance(k, (int, float)))
        icon = self.tile_icon(row)
        icon_key = (icon.get("name"), icon.get("bg"), icon.get("ink")) \
            if icon else None
        return ("grad", self._is_banded(colors, ramp), hexes, bases,
                stops, icon_key, THUMB_SIZE)

    def _decoration_image(self, index: QtCore.QModelIndex):
        """The painted swatch (or chosen icon) over the engine's PAINT
        path - this section has no thumbnail files, so the base's file
        loader never applies."""
        row = index.row()
        asset = self._assets[row]
        key = self._swatch_key(row)
        image = thumbnails.engine.peek(key)
        if image is not None:
            return image
        if self.tile_icon(row):
            composed = self._missing_thumb_image(row)
            if composed is not None:
                thumbnails.engine.deposit(key, composed)
                return composed
        colors = self._colors_of(asset)
        ramp = self._ramp_of(asset)
        image = QtGui.QImage(
            THUMB_SIZE, THUMB_SIZE, QtGui.QImage.Format.Format_RGB32
        )
        painter = QtGui.QPainter(image)
        if self._is_banded(colors, ramp):
            # Stacked horizontal bands - the dictionary's own
            # presentation, kept for the seeded palettes.
            band_h = THUMB_SIZE / max(len(colors), 1)
            for i, color in enumerate(colors):
                painter.fillRect(
                    QtCore.QRectF(0, i * band_h, THUMB_SIZE, band_h + 1),
                    QtGui.QColor(color["hex"]),
                )
        else:
            self._paint_ramp(painter, ramp)
        painter.end()
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
            painter.fillRect(0, 0, THUMB_SIZE, THUMB_SIZE,
                             QtGui.QColor("#444444"))
            return
        if all(b == "Constant" for b in bases):
            edges = list(keys) + [1.0]
            for i, value in enumerate(values):
                x0 = max(0.0, min(1.0, edges[i])) * THUMB_SIZE
                x1 = max(0.0, min(1.0, edges[i + 1])) * THUMB_SIZE
                color = QtGui.QColor.fromRgbF(*value[:3])
                painter.fillRect(
                    QtCore.QRectF(x0, 0, x1 - x0 + 1, THUMB_SIZE), color)
            return
        gradient = QtGui.QLinearGradient(0, 0, THUMB_SIZE, 0)
        for key, value in zip(keys, values):
            gradient.setColorAt(
                max(0.0, min(1.0, key)), QtGui.QColor.fromRgbF(*value[:3])
            )
        painter.fillRect(0, 0, THUMB_SIZE, THUMB_SIZE,
                         QtGui.QBrush(gradient))

    def render_thumbnail(self, index) -> None:
        """No render - the preview is drawn from the palette's own
        ramp; repaint it from current content."""
        if 0 <= index.row() < len(self._assets):
            thumbnails.engine.discard(self._swatch_key(index.row()))
            self.row_changed(index.row(),
                             [QtCore.Qt.ItemDataRole.DecorationRole])

    def data(self, index, role: int = 0):
        # LATER COLUMNS are the table's, not the row's; column 0 falls
        # through so grid mode cannot tell.
        if index.column() > 0:
            return self.column_data(index, role)
        row = index.row()
        if not 0 <= row < len(self._assets):
            return None
        asset = self._assets[row]
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return asset.name or "Gradient"
        if role in (self.RendererLabelRole, self.RendererRole):
            # Uniformly the KIND of thing, consistent with Materials'
            # `Redshift` and Textures' `HDR`. Which set or palette size
            # an entry belongs to is Category-column information.
            return "Gradient"
        if role == QtCore.Qt.ItemDataRole.ToolTipRole:
            from amaze.helpers import ui_helpers
            names = ", ".join(
                str(c.get("name", "")) for c in self._colors_of(asset))
            return ui_helpers.tooltip_text(names)
        if role == self.CategoryLabelRole:
            cats = asset.categories
            return cats[0] if cats else "Uncategorized"
        return super().data(index, role)


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
        role-scoped dataChanged."""
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
        if self._kind == "category" \
                and self._value not in _row_categories(entry):
            return False
        if self._size_filter is not None:
            fewest, most = self._size_filter
            held = len(entry.get("colors") or ())
            if held < fewest or (most is not None and held > most):
                return False
        if not self._name_filter:
            return True
        index = model.index(source_row, 0)
        name = (model.data(index, QtCore.Qt.ItemDataRole.DisplayRole)
                or "").lower()
        if self._name_filter in name:
            return True
        for color in entry["colors"]:
            if self._name_filter in color["name"].lower():
                return True
        return False
