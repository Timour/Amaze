"""Models for the Code section - reusable code snippets (VEX wrangles,
OpenCL kernels, Python SOP scripts).

Like the Cop section, a second independent material-style library over
its own code.json - CodeLibrary/CodeCategories subclass the material
machinery, so categories, favorites, tags, search, deletion, the
sidebar counts and the proxy filtering all come from the proven
material code paths. What differs:

- **Storage is INLINE text**, not a node archive - the snippet lives in
  the Material.code field (persisted through get_as_dict/from_dict like
  any other field), so code.json is fully self-contained and human-
  readable. No <id>.mat/.png files at all.
- **Thumbnails are PAINTED**, not rendered - a monospace preview of the
  first lines of code, via the unified engine's PAINT path
  (thumbnails.engine.deposit), keyed by the code's content so an edit
  mints a fresh preview.
- **The renderer field holds the LANGUAGE** ("VEX"/"OpenCL"/"Python"),
  which becomes the tile subtitle and the search/filter dimension, just
  as it names the renderer for materials.
- **Import applies the code** to a node's snippet parm (or copies it),
  instead of building a scene.
"""

import os
import json

import hou
from PySide6 import QtCore, QtGui

from amaze.core import debug, library, category, material, thumbnails
from amaze.helpers import hostos, vex_syntax

# Curated starter snippets shipped with the plugin, seeded ONCE per
# library into a "Starter Toolbox" category (see seed_starter_snippets).
# The marker file name is versioned so a future batch can seed again
# without re-adding snippets the user may have deleted from the first.
_STARTER_DEF = "res/def/starter_snippets.json"
_STARTER_MARKER = ".amaze_code_starter_v1"
#: Pre-rename marker; renamed on sight so an old library does not
#: re-seed the starter snippets and duplicate them.
_STARTER_MARKER_LEGACY = ".assetlib_code_starter_v1"


def _migrate_marker(directory: str) -> None:
    hostos.migrate_legacy_file(
        directory, _STARTER_MARKER_LEGACY, _STARTER_MARKER)

# Preview tile size - painted once per snippet content, cached in the
# shared engine like every other section's thumbnail. Rendered at 2x the
# on-tile size (512, font/margin doubled to match) so the sharp-edged
# text stays crisp when the DPI-aware delegate paints it at a Retina
# display's physical resolution - a 256px canvas got upscaled and looked
# blurry next to the photographic sections.
PREVIEW_SIZE = 512
# Font size on the PREVIEW_SIZE canvas (48 on 512 = the same visual size
# as 24 on the old 256 canvas, i.e. identical layout at 2x resolution).
PREVIEW_FONT_PX = 48
# Text inset, also 2x the old value so the layout is unchanged.
PREVIEW_MARGIN = 20


class CodeCategories(category.Categories):
    """The Code section's category sidebar - same model, own database."""

    DB_FILENAME = "code.json"


class CodeLibrary(library.AssetLibrary):
    """The Code section's asset model - the shared engine over
    code.json, storing snippet text inline and painting a preview."""

    NOTES_SECTION = "code"

    DB_FILENAME = "code.json"

    #: Snippets are stored INLINE, so a refused list write leaves
    #: nothing on disk to recover and Repair has nothing to put back -
    #: the message must say the snippet was not saved, rather than the
    #: base class's "the files are there".
    CONTENT_SURVIVES_A_REFUSED_INDEX_WRITE = False

    def cleanup_db(self, show_dialog: bool = True) -> int:
        """Code snippets live INLINE in code.json - there are no
        <id>.mat/.interface/thumbnail files - so the inherited cleanup's
        missing-file and lonely-file passes would classify EVERY snippet
        as an orphan and delete the whole library. Deliberately reduced
        to a state flush."""
        self.save()
        # A LIST, matching the base contract - the panel joins the
        # lines; a bare string would be joined character by character.
        self.last_cleanup_summary = [
            "Code: nothing to clean (snippets are stored inline)."
        ]
        return 0

    def add_asset(
        self,
        code: str,
        name: str,
        language: str,
        cats: str,
        tags: str,
        fav: bool,
        description: str = "",
    ) -> str:
        """Register a code snippet. Returns the language string on
        success (the renderer-string contract add_asset has), "" on
        failure (empty code)."""
        if not code.strip():
            return ""
        new_mat = material.Material()
        tags = self.sanitize_tags(tags)
        new_mat.set_data(
            name.strip() or "Snippet", cats, tags, fav, language or "Code"
        )
        new_mat.code = code
        new_mat.description = description
        # Proper insert signals: rowsInserted fired ZERO times while
        # rowCount went 0 -> 1, so the dataChanged that follows named a
        # row attached views did not know existed. MaterialLibrary gets
        # this right; this subclass had regressed.
        row = len(self._assets)
        self.beginInsertRows(QtCore.QModelIndex(), row, row)
        try:
            self._assets.append(new_mat)
        finally:
            self.endInsertRows()
        self.rebuild_thumbs()
        # A snippet lives INLINE in code.json, so a refused write
        # orphans no files - but the snippet the user just watched
        # appear is not saved, and they were told nothing. Same missing
        # return-value check the other two add_assets had.
        if not self.save():
            self.report_refused_index_write(new_mat)
        # Repaint the new row's tile.
        row = self.rowCount() - 1
        self.row_changed(row, [QtCore.Qt.ItemDataRole.DecorationRole])
        return language or "Code"

    def update_asset(
        self,
        row: int,
        code: str,
        name: str,
        language: str,
        cats: str,
        tags: str,
        description: str = "",
    ) -> bool:
        """Overwrite an existing snippet's content and metadata (the
        Edit flow). Keeps the id and favorite."""
        if not 0 <= row < len(self._assets):
            return False
        asset = self._assets[row]
        asset.set_data(
            name.strip() or asset.name,
            cats,
            self.sanitize_tags(tags),
            asset.fav,
            language or "Code",
        )
        asset.code = code
        asset.description = description
        # Content changed -> the preview key changes; drop the old one.
        thumbnails.engine.discard(self._preview_key(asset))
        self.rebuild_thumbs()
        self.save()
        self.row_changed(row)
        return True

    def data(self, index, role=0):
        """Hover tooltip: the snippet's name, plus its description when it
        has one (curated starter snippets ship with a description; user
        snippets can be given one in the Edit dialog). Everything else
        falls through to the material machinery."""
        if role == QtCore.Qt.ItemDataRole.ToolTipRole:
            from amaze.helpers import ui_helpers

            desc = self._assets[index.row()].description
            # Just the description (no name - it's already on the tile),
            # word-wrapped in a max-width box.
            return ui_helpers.tooltip_text(desc) if desc else None
        return super().data(index, role)

    # -- curated starter toolbox --------------------------------------

    def seed_starter_snippets(self, category_model) -> None:
        """Seed a curated "Starter Toolbox" category of useful snippets
        into this library, ONCE. Guarded by a versioned marker file in
        the library dir so deleting a seeded snippet doesn't bring it
        back, and existing user snippets are never touched. Best-effort:
        any failure (missing/broken def file, no library dir) is printed
        and swallowed so it can never block panel startup."""
        try:
            lib_dir = self.preferences.dir
            if not lib_dir:
                return
            # The starter category first shipped as "Starter Toolbox";
            # it was later shortened to "Toolbox". Rename it in place in
            # already-seeded libraries. Runs BEFORE the marker check
            # (which would otherwise short-circuit) and is idempotent -
            # a no-op once nothing named "Starter Toolbox" remains.
            self._rename_category(
                category_model, "Starter Toolbox", "Toolbox"
            )
            _migrate_marker(lib_dir)
            marker = os.path.join(lib_dir, _STARTER_MARKER)
            if os.path.exists(marker):
                return
            def_path = os.path.join(
                hou.getenv("AMAZE") or "",
                "scripts/python/amaze",
                _STARTER_DEF,
            )
            if not os.path.exists(def_path):
                return
            with open(def_path, encoding="utf-8") as f:
                data = json.load(f)
            cat = data.get("category", "Starter Toolbox")
            snippets = data.get("snippets", [])
            added = 0
            for snip in snippets:
                code = snip.get("code", "")
                if not code.strip():
                    continue
                mat = material.Material()
                mat.set_data(
                    snip.get("name", "Snippet"),
                    cat,
                    "",  # tags
                    False,  # favorite
                    snip.get("language", "VEX"),
                )
                mat.code = code
                mat.description = snip.get("description", "")
                row = len(self._assets)
                self.beginInsertRows(QtCore.QModelIndex(), row, row)
                try:
                    self._assets.append(mat)
                finally:
                    self.endInsertRows()
                added += 1
            if added:
                self.rebuild_thumbs()
                # The marker below may only be written if the snippets
                # actually REACHED disk. save() reports its refusals by
                # returning False rather than raising (a held file, a
                # blocked write, a refused merge) - and the exists()
                # gate further down cannot see those, because in every
                # one of them code.json is still sitting there from
                # before. Withhold instead: nothing was persisted, so
                # re-seeding next launch cannot duplicate anything.
                # Same shape as gradient_library's curated seed.
                if not self.save():
                    debug.event("session", "starter snippets not marked "
                                "- the save did not reach disk")
                    return
                # Register the category so it appears in the sidebar (the
                # category list is a separate model over the SAME shared
                # code.json db dict - see core/database.py).
                category_model.check_add_category(cat)
        except Exception as exc:  # noqa: BLE001 - never block startup
            # note vs event for this file: this failure is internal - a
            # raw exception on a first-run nicety, with nothing the user
            # can do about it - so event. The marker failure below states
            # a consequence they can observe, so that one is a note.
            debug.event("session", "starter snippet seeding failed",
                        error=str(exc))
            return
        # The marker is written OUTSIDE the try that wraps the save, and
        # a failure to write it is a HARD STOP for this library rather
        # than a print.
        #
        # Both were inside one broad handler before. If the save
        # succeeded and the marker write failed, the next launch seeded
        # again - duplicate starter snippets, growing per launch. If the
        # save failed, the model showed seeded content that was never
        # persisted, and the first user edit persisted a partial set.
        # Written even when nothing was added, so a broken/empty def
        # file is not retried on every launch.
        #
        # NOT written when code.json is not on disk. The marker is what
        # the absent-database guard reads as "this database was here"
        # (code.json is the one with no .bak on the real library, so the
        # marker is its ONLY trace) - and database.save() reports an
        # OSError to the user instead of raising, so a save held off by
        # a full disk or a cloud-sync lock lands here looking successful.
        # A marker with no database behind it refuses code.json on every
        # future launch and blocks writes for the session: the Code
        # section can never be saved again, curable only by deleting a
        # dotfile. Retrying the seed next launch cannot duplicate
        # anything, because nothing reached disk.
        if not os.path.exists(os.path.join(lib_dir, self.DB_FILENAME)):
            debug.event("session", "snippet seed marker withheld - the "
                        "database is not on disk", file=lib_dir)
            return
        try:
            with open(marker, "w", encoding="utf-8") as handle:
                handle.write("seeded\n")
        except OSError as exc:
            debug.exception("snippet seed marker", exc, marker=marker)
            debug.note(
                "the starter snippets are in your Code library, but "
                "adding them could not be recorded (%s) - so they "
                "will be added a second time when Houdini next "
                "starts. Nothing you saved yourself is affected, and "
                "you can delete any duplicates from the Toolbox "
                "category." % exc)
            # A RECORD, not a guard. The marker file is the only thing
            # the seed loop above reads, and it is what just failed to
            # write, so nothing here prevents the re-seed - which is why
            # the message says it will happen instead of claiming it was
            # avoided. Nothing reads this attribute yet; the earlier
            # wording promised it did.
            self._seed_marker_failed = True
            return
        if added:
            debug.event(
                "session", "snippets seeded", count=added, category=cat
            )

    def _rename_category(self, category_model, old: str, new: str) -> None:
        """Rename a category in place: every snippet filed under `old`
        moves to `new`, and the sidebar category list follows. Idempotent
        (no-op when nothing uses `old`). Both models share one code.json
        db dict, so saving each persists the whole file."""
        changed = False
        for asset in self._assets:
            if old in asset.categories:
                cats = [new if c == old else c for c in asset.categories]
                asset.categories = ",".join(dict.fromkeys(cats))  # dedup
                changed = True
        if changed:
            self.save()
        cats = category_model._categories
        if old in cats:
            if new in cats:
                category_model.remove_category(old)  # merge, no duplicate
            else:
                category_model.rename_category(old, new)

    # -- painted preview thumbnail ------------------------------------

    @staticmethod
    def _preview_key(asset):
        """Content-addressed: the code text + language, so an edit mints
        a new key (and the old preview ages out of the shared LRU)."""
        return ("code", asset.mat_id, hash(asset.code), asset.renderer)

    def _decoration_image(self, index: QtCore.QModelIndex):
        asset = self._assets[index.row()]
        # A chosen tile icon replaces the code preview - this section
        # has no thumbnail FILE, so the base class's path (which swaps
        # the file path) never applies here and the choice would be
        # accepted, saved, and then ignored forever.
        chosen = self._missing_thumb_image(index.row()) \
            if self.tile_icon(index.row()) else None
        if chosen is not None:
            return chosen
        key = self._preview_key(asset)
        image = thumbnails.engine.peek(key)
        if image is not None:
            return image
        image = self._paint_preview(asset)
        thumbnails.engine.deposit(key, image)
        return image

    def _paint_preview(self, asset) -> QtGui.QImage:
        image = QtGui.QImage(
            PREVIEW_SIZE, PREVIEW_SIZE, QtGui.QImage.Format.Format_RGB32
        )
        # Black field like Houdini's wrangle editor, same palette.
        image.fill(vex_syntax.BACKGROUND)
        painter = QtGui.QPainter(image)
        try:
            font = QtGui.QFont("Courier New")
            font.setStyleHint(QtGui.QFont.StyleHint.Monospace)
            font.setPixelSize(PREVIEW_FONT_PX)
            font.setBold(True)
            painter.setFont(font)
            metrics = QtGui.QFontMetrics(font)
            line_h = metrics.height()
            margin = PREVIEW_MARGIN
            y = margin + metrics.ascent()
            bottom = PREVIEW_SIZE - margin
            # Monospace, so one column width fits every glyph; wrap long
            # source lines onto more visual rows (soft-wrap) instead of
            # truncating them at the right edge.
            char_w = max(1, metrics.horizontalAdvance("m"))
            cols = max(1, (PREVIEW_SIZE - 2 * margin) // char_w)
            default = vex_syntax.DEFAULT
            for line in asset.code.split("\n"):
                if y > bottom:
                    break
                expanded = line.replace("\t", "    ")
                if not expanded:
                    y += line_h  # blank line still takes a row
                    continue
                # Per-character color from the syntax spans, so coloring
                # survives the wrap.
                char_colors = [default] * len(expanded)
                for start, length, color in vex_syntax.spans(expanded):
                    for i in range(start, min(start + length, len(expanded))):
                        char_colors[i] = color
                # Emit the line in cols-wide chunks, one visual row each.
                for cstart in range(0, len(expanded), cols):
                    if y > bottom:
                        break
                    chunk = expanded[cstart:cstart + cols]
                    cc = char_colors[cstart:cstart + cols]
                    # Draw consecutive same-color runs in one go.
                    i = 0
                    while i < len(chunk):
                        j = i
                        while j < len(chunk) and cc[j] == cc[i]:
                            j += 1
                        painter.setPen(cc[i])
                        painter.drawText(
                            margin + i * char_w, y, chunk[i:j]
                        )
                        i = j
                    y += line_h
        finally:
            painter.end()
        return image

    # -- apply to a node ----------------------------------------------

    def apply_to_node(self, row: int, node: hou.Node):
        """Set the snippet onto a node's code parm. Returns (ok, reason)
        so the panel can report a node with no code parm."""
        from amaze.helpers import helpers

        if not 0 <= row < len(self._assets):
            return (False, "No snippet selected.")
        if node is None:
            return (False, "Select a node with a code/snippet parameter.")
        parm = helpers.find_code_parm(node)
        if parm is None:
            return (
                False,
                '"%s" has no code/snippet parameter to set.' % node.name(),
            )
        try:
            parm.set(self._assets[row].code)
        except hou.OperationFailed as exc:
            return (False, "Could not set the parameter: %s" % exc)
        return (True, "")

    # The material overrides that make no sense for inline text: a code
    # snippet has no node archive to import or thumbnail to render.
    def import_asset_to_scene(self, index, target="auto", context_node=None):
        """Double-click applies the snippet to the selected node.
        Returns (ok, reason, created) like every import - created is
        always empty here, since applying text creates nothing."""
        node = None
        sel = hou.selectedNodes()
        if len(sel) == 1:
            node = sel[0]
        ok, reason = self.apply_to_node(index.row(), node)
        return ok, reason, []

    def render_thumbnail(self, index) -> None:
        """No render - repaint the preview from current content."""
        if 0 <= index.row() < len(self._assets):
            thumbnails.engine.discard(
                self._preview_key(self._assets[index.row()])
            )
            self.row_changed(index.row(), [QtCore.Qt.ItemDataRole.DecorationRole])
