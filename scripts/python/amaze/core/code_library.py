"""Models for the Code section - reusable code snippets (VEX wrangles, OpenCL kernels, Python SOP scripts): a material-style library over its own code.json, CodeLibrary/CodeCategories subclassing the material machinery. Storage is INLINE text, not a node archive - the snippet lives in the Material.code field, persisted through get_as_dict/from_dict like any other field, so code.json is fully self-contained and there are no <id>.mat/.png files at all. Thumbnails are PAINTED, not rendered: a monospace preview of the first lines of code via the unified engine's PAINT path (thumbnails.engine.deposit), keyed by the code's content so an edit mints a fresh preview. The renderer field holds the LANGUAGE ("VEX"/"OpenCL"/"Python"), which becomes the tile subtitle and the search/filter dimension. Import applies the code to a node's snippet parm (or copies it), instead of building a scene."""

import os
import json
import shutil
import tempfile

from PySide6 import QtCore, QtGui

import amaze
from amaze import amazetheme
from amaze.core import debug, library, category, material, thumbnails, tile_icons, versions

_STARTER_DEF = "res/def/starter_snippets.json"  # example snippets shipped with the plugin, seeded ONCE per library into an "Examples" category (see seed_starter_snippets)
_STARTER_MARKER = ".amaze_code_starter_v1"  # the marker file name is versioned, so a future batch can seed again without re-adding snippets the user may have deleted from the first

PREVIEW_SIZE = 512  # preview tile size, painted once per snippet content and cached in the shared engine: 2x the 256 on-tile size (font/margin doubled to match) so the sharp-edged text stays crisp when the DPI-aware delegate paints it at a Retina display's physical resolution - a 256px canvas got upscaled and looked blurry
PREVIEW_FONT_PX = 48  # font size on the PREVIEW_SIZE canvas: 48 on 512 is the same visual size as 24 on a 256 canvas, i.e. identical layout at 2x resolution
PREVIEW_MARGIN = 20  # text inset, also 2x the 256-canvas value so the layout is unchanged


def paint_code_preview(code: str) -> QtGui.QImage:
    """The Code section's tile face for a snippet: a syntax-colored monospace preview on a PREVIEW_SIZE square, soft-wrapping long source lines and stopping at the bottom margin - shared with the online browser's amazepkg snippet tiles."""
    from amaze.helpers import vex_syntax
    image = QtGui.QImage(
        PREVIEW_SIZE, PREVIEW_SIZE, QtGui.QImage.Format.Format_RGB32
    )
    image.fill(QtGui.QColor(amazetheme.CODE_TILE_GROUND))
    text = QtGui.QImage(PREVIEW_SIZE, PREVIEW_SIZE,
                        QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    text.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(text)    # one layer, faded whole below: overlapping glyphs stay even
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
        char_w = max(1, metrics.horizontalAdvance("m"))  # monospace, so one column width fits every glyph
        cols = max(1, (PREVIEW_SIZE - 2 * margin) // char_w)  # long source lines wrap onto more visual rows (soft-wrap) instead of truncating at the right edge
        default = vex_syntax.DEFAULT
        for line in str(code or "").split("\n"):
            if y > bottom:
                break
            expanded = line.replace("\t", "    ")
            if not expanded:
                y += line_h  # blank line still takes a row
                continue
            char_colors = [default] * len(expanded)  # per-character color from the syntax spans, so coloring survives the wrap
            for start, length, color in vex_syntax.spans(expanded):
                for i in range(start, min(start + length, len(expanded))):
                    char_colors[i] = color
            for cstart in range(0, len(expanded), cols):  # emit the line in cols-wide chunks, one visual row each
                if y > bottom:
                    break
                chunk = expanded[cstart:cstart + cols]
                cc = char_colors[cstart:cstart + cols]
                i = 0  # draw consecutive same-color runs in one go
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
    layer = QtGui.QPainter(image)
    layer.setOpacity(amazetheme.CODE_TEXT_OPACITY)
    layer.drawImage(0, 0, text)
    layer.end()
    return image


def _staged(text) -> dict:
    """A snippet's text as the one file the version engine copies, {suffix: path}; {} failed."""
    folder = ""
    try:
        folder = tempfile.mkdtemp(prefix="amaze_code_base_")
        path = os.path.join(folder, "base" + versions.CODE_SUFFIX)
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(str(text or ""))
    except (OSError, ValueError) as exc:
        if folder:
            shutil.rmtree(folder, ignore_errors=True)
        debug.event("versions", "code text not staged", error=str(exc))
        return {}
    return {versions.CODE_SUFFIX: path}


def _unstage(*staged) -> None:
    for paths in staged:
        for path in paths.values():
            shutil.rmtree(os.path.dirname(path), ignore_errors=True)


class CodeCategories(category.Categories):
    """The Code section's category sidebar - same model, own database."""

    DB_FILENAME = "code.json"


class CodeLibrary(library.AssetLibrary):
    """The Code section's asset model - the shared engine over code.json, storing snippet text inline and painting a preview."""

    NOTES_SECTION = "code"
    TILE_FACE = "face_code"    # T05

    DB_FILENAME = "code.json"
    VERSION_SECTION = versions.CODE    # code/versions/<id>/, the text handed in as a file
    NEW_VERSION = 0    # save_version's number for a version the editor has not saved yet

    CONTENT_SURVIVES_A_REFUSED_INDEX_WRITE = False  # snippets are stored INLINE, so a refused list write leaves nothing on disk to recover and Repair has nothing to put back - the message must say the snippet was not saved, rather than the base class's "the files are there"

    def add_asset(
        self,
        code: str,
        name: str,
        language: str,
        cats: str,
        tags: str,
        fav: bool,
    ) -> str:
        """Register a code snippet. Returns the language string on success (the renderer-string contract add_asset has), "" on failure (empty code)."""
        return (language or "Code") if self.add_snippet(code, name, language, cats, tags) else ""

    def add_snippet(self, code: str, name: str, language: str, cats: str, tags: str) -> str:
        """Register a snippet and answer its id, empty for no code. A refused list write is said."""
        if not code.strip():
            return ""
        new_mat = material.Material()
        new_mat.set_data(name.strip() or "Snippet", cats, self.sanitize_tags(tags), False,
                         language or "Code")
        new_mat.code = code
        self._append_record(new_mat)
        if not self.save():    # inline, so nothing is left on disk: the user must hear it
            self.report_refused_index_write(new_mat)
        return str(new_mat.mat_id)

    def save_from_editor(self, mat_id: str, version, code: str, name: str, language: str,
                         cats: str, tags: str) -> str:
        """One Apply in the code dialog: a new snippet for an empty id, else into `version`."""
        if not mat_id:
            return self.add_snippet(code, name, language, cats, tags)
        row = self.find_asset_row_by_id(mat_id)    # a save can move rows
        if row < 0:
            debug.event("code", "edited snippet gone from the library", mat_id=mat_id)
            return ""
        if version is None:    # a snippet that keeps no versions
            self.update_asset(row, code, name, language, cats, tags)
        elif not self.save_version(row, version, code, name, language, cats, tags):
            return ""
        return mat_id

    def update_asset(
        self,
        row: int,
        code: str,
        name: str,
        language: str,
        cats: str,
        tags: str,
    ) -> bool:
        """Overwrite an existing snippet's content and metadata (the Edit flow). Keeps the id and favorite."""
        if not 0 <= row < len(self._assets):
            return False
        self._write_snippet(self._assets[row], code, name, language, cats, tags)
        return True

    def _write_snippet(self, asset, code, name, language, cats, tags) -> bool:
        """Set a snippet's text and fields and save the list; True when the save landed."""
        asset.set_data(name.strip() or asset.name, cats, self.sanitize_tags(tags),
                       asset.fav, language or "Code")
        return self._store_text(asset, code)

    def _store_text(self, asset, code: str) -> bool:
        key_before = self._preview_key(asset)    # the OLD content's key: taken after, it misses
        asset.code = code
        thumbnails.engine.discard(key_before)
        self.rebuild_thumbs()
        return self._saved_rows_changed([asset])

    def version_text(self, row: int, number: int):
        """Version `number`'s text for the editor to show; None when its file cannot be read."""
        if not 0 <= row < len(self._assets):
            return None
        mat_id = str(self._assets[row].mat_id)
        try:
            with open(versions.version_file(self.preferences, mat_id, number, versions.CODE),
                      encoding="utf-8", newline="") as handle:
                return handle.read()
        except (OSError, ValueError) as exc:    # "" names no file, and lands here too
            debug.event("versions", "code version unreadable", mat_id=mat_id, n=number,
                        error=str(exc))
            return None

    def save_version(self, row: int, number: int, code: str, name: str, language: str,
                     cats: str, tags: str) -> bool:
        """The editor's Apply: version `number`, or a new one, holds `code` and is the active one."""
        if not 0 <= row < len(self._assets):
            return False
        asset = self._assets[row]
        mat_id = str(asset.mat_id)
        name = str(name or "").strip() or asset.name    # a tile shows its active version's name
        held, typed = _staged(asset.code), _staged(code)
        try:
            if not (held and typed) or not versions.keep_base(
                    self.preferences, mat_id, versions.CODE, held, asset.name):
                return False
            active = versions.active_version(self.preferences, mat_id, versions.CODE)
            if number not in (self.NEW_VERSION, active) and not versions.switch_active(
                    self.preferences, mat_id, number, versions.CODE, held):
                return False
            if not self._write_snippet(asset, code, name, language, cats, tags):
                self.report_refused_index_write(asset)
                return False
            if number == self.NEW_VERSION:
                return bool(versions.create_version(
                    self.preferences, mat_id, name, typed, versions.CODE))
            return versions.record_base(
                self.preferences, mat_id, versions.CODE_SUFFIX, versions.CODE,
                typed[versions.CODE_SUFFIX]) and versions.rename_version(
                    self.preferences, mat_id, number, name, versions.CODE)
        finally:
            _unstage(held, typed)
            self._versions_changed(asset)

    def switch_version(self, row: int, number: int) -> bool:
        """Make version `number` the snippet's text and name, as Select does in the Versions dialog."""
        if not 0 <= row < len(self._assets):
            return False
        asset = self._assets[row]
        mat_id = str(asset.mat_id)
        held = _staged(asset.code)
        try:
            if not held or not versions.switch_active(
                    self.preferences, mat_id, number, versions.CODE, held, asset.name):
                return False
            with open(held[versions.CODE_SUFFIX], encoding="utf-8", newline="") as handle:
                code = handle.read()
            asset.name = versions.active_version_name(
                self.preferences, mat_id, versions.CODE) or asset.name
            asset.set_current_date()
            if not self._store_text(asset, code):
                self.report_refused_index_write(asset)
                return False
            return True
        except OSError as exc:
            debug.event("versions", "switched code version unreadable", mat_id=mat_id,
                        n=number, error=str(exc))
            return False
        finally:
            _unstage(held)
            self._versions_changed(asset)

    def row_data(self, row, role):
        """The tooltip is the snippet's own comment ▸p/d03-retired; the rest is the base's."""
        if role == QtCore.Qt.ItemDataRole.ToolTipRole:
            from amaze.core import notes

            page = notes.note_for(
                self.preferences,
                notes.note_key(self.NOTES_SECTION,
                               str(self._assets[row].mat_id)))
            said = "\n".join(item.get("text", "")    # TEXT blocks only, never a to-do or a picture
                             for item in page.get("items", [])
                             if item.get("t") == "text").strip()
            return said or None  # no name: the tile shows it
        return super().row_data(row, role)

    def seed_starter_snippets(self, category_model) -> None:
        """Seed an "Examples" category of snippets into this library, ONCE. Guarded by a versioned marker file in the library dir so deleting a seeded snippet doesn't bring it back, and existing user snippets are left alone. Best-effort: any failure (missing/broken def file, no library dir) is printed and swallowed so it can never block panel startup."""
        try:
            lib_dir = self.preferences.dir
            if not lib_dir:
                return
            marker = os.path.join(lib_dir, _STARTER_MARKER)
            if os.path.exists(marker):
                return
            def_path = amaze.package_file(_STARTER_DEF)
            if not os.path.exists(def_path):
                return
            with open(def_path, encoding="utf-8") as f:
                data = json.load(f)
            cat = data.get("category", "Examples")
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
                mat._extra["curated"] = (    # the stable identity a restore matches on, riding the record's extra-keys courtesy
                    "starter/%s" % snip.get("name", "Snippet"))
                self._append_record(mat)
                added += 1
            if added:
                self.adopt_retired_text_into_notes()    # the curated snippets ship a description, which is a COMMENT now - moved here so it lands this session rather than on the next open ▸p/d03-retired
                if not self.save():  # the marker below may only be written if the snippets actually REACHED disk: save() reports its refusals (a held file, a blocked write, a refused merge) by returning False rather than raising, and the exists() gate further down cannot see those, because in every one of them code.json is still sitting there from before
                    debug.event("session", "starter snippets not marked "
                                "- the save did not reach disk")
                    return  # withhold instead: nothing was persisted, so re-seeding next launch cannot duplicate anything
                category_model.check_add_category(cat)  # register the category so it appears in the sidebar - the category list is a separate model over the SAME shared code.json db dict, see core/database.py
        except Exception as exc:  # noqa: BLE001 - never block startup
            debug.event("session", "starter snippet seeding failed",  # event, not note: this failure is internal, a raw exception on a first-run nicety with nothing the user can do about it
                        error=str(exc))
            return
        if not os.path.exists(os.path.join(lib_dir, self.DB_FILENAME)):  # the marker is NOT written when code.json is not on disk: it is what the absent-database guard reads as "this database was here", and code.json is the one with no .bak on the real library, so the marker is its ONLY trace
            debug.event("session", "snippet seed marker withheld - the "
                        "database is not on disk", file=lib_dir)
            return  # database.save() reports an OSError to the user instead of raising, so a save held off by a full disk or a cloud-sync lock lands here looking successful; a marker with no database behind it then refuses code.json on every future launch and blocks writes for the session, curable only by deleting a dotfile, while retrying the seed cannot duplicate anything because nothing reached disk
        try:
            with open(marker, "w", encoding="utf-8", newline="\n") as handle:  # written OUTSIDE the try that wraps the save, and even when nothing was added, so a broken or empty def file is not retried on every launch
                handle.write("seeded\n")
        except OSError as exc:
            debug.exception("snippet seed marker", exc, marker=marker)
            debug.note(  # note, not event: this states a consequence the user can observe
                "the starter snippets are in your Code library, but "
                "adding them could not be recorded (%s) - so they "
                "will be added a second time when Houdini next "
                "starts. Nothing you saved yourself is affected, and "
                "you can delete any duplicates from the Examples "
                "category." % exc)
            self._seed_marker_failed = True  # a RECORD, not a guard: nothing reads this attribute, and the marker file is the only thing the seed loop above reads, so nothing here prevents the re-seed - which is why the message says it will happen
            return
        if added:
            debug.event(
                "session", "snippets seeded", count=added, category=cat
            )

    @staticmethod
    def _preview_key(asset):
        """Content-addressed: the code text + language, so an edit mints a new key (and the old preview ages out of the shared LRU)."""
        return ("code", asset.mat_id, hash(asset.code), asset.renderer)

    def _decoration_image(self, row: int):
        """The tile image: a chosen icon, else the painted code preview, painted on a miss."""
        asset = self._assets[row]
        face = tile_icons.face_for(self, row)
        if face == "capture":
            return super()._decoration_image(row)    # the capture PNG, through the shared loader
        if face != "preview":    # no thumbnail FILE to swap here
            return self._missing_thumb_image(row)
        key = self._preview_key(asset)
        image = thumbnails.engine.peek(key)
        if image is not None:
            return image
        image = self._paint_preview(asset)
        thumbnails.engine.deposit(key, image)
        return image

    def preview_image(self, row: int):
        """The painted code, for the Customize preview."""
        return self._paint_preview(self._assets[row]) if 0 <= row < len(self._assets) else None

    def _paint_preview(self, asset) -> QtGui.QImage:
        return paint_code_preview(asset.code)
