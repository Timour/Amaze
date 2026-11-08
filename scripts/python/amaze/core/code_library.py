"""The Code section's library: snippets inline in code.json, the `renderer` field their language."""

import os
import json
import shutil
import tempfile

from PySide6 import QtCore, QtGui

import amaze
from amaze import amazetheme
from amaze.core import debug, library, category, material, thumbnails, tile_icons, versions

_STARTER_DEF = "res/def/starter_snippets.json"  # shipped example snippets, seeded once per library
_STARTER_MARKER = ".amaze_code_starter_v1"  # versioned: a new name seeds again

PREVIEW_SIZE = 512  # preview canvas, twice the on-tile size so text stays crisp on Retina
PREVIEW_FONT_PX = 48  # font size on the PREVIEW_SIZE canvas
PREVIEW_MARGIN = 20  # text inset, also 2x the 256-canvas value so the layout is unchanged


def paint_code_preview(code: str) -> QtGui.QImage:
    """A snippet's tile face: a syntax-coloured, soft-wrapped monospace preview, PREVIEW_SIZE square."""
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
        cols = max(1, (PREVIEW_SIZE - 2 * margin) // char_w)  # long lines wrap rather than truncate
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
    """The Code section's asset model over code.json, snippet text inline, previews painted."""

    NOTES_SECTION = "code"
    TILE_FACE = "face_code"    # T05

    DB_FILENAME = "code.json"
    VERSION_SECTION = versions.CODE    # code/versions/<id>/, the text handed in as a file
    NEW_VERSION = 0    # save_version's number for a version the editor has not saved yet

    def add_asset(
        self,
        code: str,
        name: str,
        language: str,
        cats: str,
        tags: str,
        fav: bool,
    ) -> str:
        """Register a code snippet: its language on success, "" for empty code."""
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
        if not self.save():    # inline, so it lives in memory until the next save that works
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
                self.report_refused_index_write(asset, updated=True)
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
                self.report_refused_index_write(asset, updated=True)
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
        """Seed an "Examples" category of snippets once per library, by a marker file; never raises."""
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
                self.adopt_retired_text_into_notes()    # descriptions move to the COMMENT ▸p/d03-retired
                if not self.save():  # no marker unless the snippets reached disk
                    debug.event("session", "starter snippets not marked "
                                "- the save did not reach disk")
                    return  # withhold instead: nothing was persisted, so re-seeding next launch cannot duplicate anything
                category_model.check_add_category(cat)  # so the category shows in the sidebar
        except Exception as exc:  # noqa: BLE001 - never block startup
            debug.event("session", "starter snippet seeding failed",  # an event: nothing for the user to do
                        error=str(exc))
            return
        if not os.path.exists(os.path.join(lib_dir, self.DB_FILENAME)):  # no marker without code.json on disk
            debug.event("session", "snippet seed marker withheld - the "
                        "database is not on disk", file=lib_dir)
            return
        try:
            with open(marker, "w", encoding="utf-8", newline="\n") as handle:  # written even when nothing was added
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
            self._seed_marker_failed = True  # a record only; the next launch seeds again
            return
        if added:
            debug.event(
                "session", "snippets seeded", count=added, category=cat
            )

    @staticmethod
    def _preview_key(asset):
        """The preview key from the code text and language, so an edit mints a new one."""
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
