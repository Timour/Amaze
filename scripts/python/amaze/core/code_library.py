"""The Code section's library: snippets inline in code.json, the `renderer` field is the language."""

import functools
import json

from PySide6 import QtCore, QtGui

import amaze
from amaze import amazetheme
from amaze import messages
from amaze.core import debug, library, library_files, category, material
from amaze.core import thumbnails

_STARTER_DEF = "res/def/starter_snippets.json"  # shipped example snippets, seeded once per library
_STARTER_MARK = "code_starter_v1"  # in the library's marks; versioned: a new name seeds again

PREVIEW_SIZE = 512  # preview canvas, twice the on-tile size so text stays crisp on Retina
PREVIEW_FONT_PX = 48  # font size on the PREVIEW_SIZE canvas
PREVIEW_MARGIN = 20  # text inset, also 2x the 256-canvas value so the layout is unchanged


def paint_code_preview(code: str) -> QtGui.QImage:
    """A snippet's tile face: a syntax-coloured, soft-wrapped monospace preview, PREVIEW_SIZE square."""
    from amaze.helpers import vex_syntax
    image = QtGui.QImage(
        PREVIEW_SIZE, PREVIEW_SIZE, QtGui.QImage.Format.Format_RGB32
    )
    image.fill(QtGui.QColor(amazetheme.TILE_GROUND))
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
            char_colors = [default] * len(expanded)  # per-character color from the syntax spans, so wrapped rows keep their coloring
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


class CodeCategories(category.Categories):
    """The Code section's category sidebar - same model, own database."""

    DB_FILENAME = library_files.CODE


class CodeLibrary(library.AssetLibrary):
    """The Code section's asset model over code.json, snippet text inline, previews painted."""

    NOTES_SECTION = "code"
    TILE_FACE = "face_code"    # T05

    DB_FILENAME = library_files.CODE

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
        """Add a snippet and return its id; empty for no code, or when the library refused it."""
        if not code.strip():
            return ""
        new_mat = material.Material()
        new_mat.set_data(name.strip() or "Snippet", cats, tags, False, language or "Code")
        new_mat.code = code
        if not self.add_saved(new_mat):    # nothing was saved: no row is shown
            debug.refuse(messages.ASSET_NOT_SAVED_DATABASE_REFUSED % new_mat.name)
            return ""
        return str(new_mat.mat_id)

    def save_from_editor(self, mat_id: str, code: str, name: str, language: str,
                         cats: str, tags: str) -> str:
        """Apply in the code dialog: a new snippet for an empty id, else the snippet saved over."""
        if not mat_id:
            return self.add_snippet(code, name, language, cats, tags)
        row = self.find_asset_row_by_id(mat_id)    # a save can move rows
        if row < 0:
            debug.event("code", "edited snippet gone from the library", mat_id=mat_id)
            return ""
        if not self.takes_edits():    # refused: the snippet keeps its old text, the user is told
            return ""
        self._write_snippet(self._assets[row], code, name, language, cats, tags)
        return mat_id

    def _write_snippet(self, asset, code, name, language, cats, tags) -> bool:
        """Set a snippet's text and fields and save the list; True when the save succeeded."""
        asset.set_data(name.strip() or asset.name, cats, tags, asset.fav, language or "Code")
        return self._store_text(asset, code)

    def _store_text(self, asset, code: str) -> bool:
        key_before = self._preview_key(asset)    # the OLD content's key: read after the change, it would not match
        asset.code = code
        thumbnails.engine.discard(key_before)
        self.rebuild_thumbs()
        return self._saved_rows_changed([asset])

    def _info_facts(self, row: int, asset) -> tuple:
        """Language, the Type column, and the number of lines in the snippet's text."""
        return [("Language", str(self.row_data(row, self.RendererLabelRole) or "")),
                ("Lines", str(len(asset.code.splitlines())))], None

    def row_data(self, row, role):
        """The tooltip is the snippet's own comment ▸p/d03-retired; the rest is AssetLibrary's."""
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
        if role == self.RunningRole:
            return bool(self._running) and str(self._assets[row].mat_id) == self._running
        return super().row_data(row, role)

    RunningRole = QtCore.Qt.ItemDataRole.UserRole + 17    # True for the snippet Run is running now
    _running = ""    # that snippet's id, "" while none runs

    def running(self) -> str:
        """The id of the snippet Run is running, "" for none."""
        return self._running

    def set_running(self, mat_id: str) -> None:
        """`mat_id`'s snippet runs now, "" for none: the rows whose running mark changes repaint."""
        rows = {self.find_asset_row_by_id(one) for one in (self._running, mat_id) if one}
        self._running = str(mat_id or "")
        for row in rows:
            self.row_changed(row, [self.RunningRole])

    def seed_starter_snippets(self, category_model) -> int:
        """The shipped `Examples` snippets added once per library; how many were added."""
        from amaze.core import notes
        records, pages = [], {}
        try:
            with open(amaze.package_file(_STARTER_DEF), encoding="utf-8") as f:
                data = json.load(f)
            for snip in (snip for snip in data.get("snippets", []) if snip.get("code", "").strip()):
                mat = material.Material()
                mat.set_data(snip.get("name", "Snippet"), data.get("category", "Examples"), "",
                             False, snip.get("language", "VEX"))
                mat.code = snip["code"]
                mat._extra["curated"] = "starter/" + snip.get("name", "Snippet")    # restores match it
                text = str(snip.get("description", "") or "").strip()
                if text:    # a snippet's description is its comment
                    pages[notes.note_key(self.NOTES_SECTION, mat.mat_id)] = [
                        {"t": "text", "text": text}]
                records.append(mat)
        except (OSError, ValueError, AttributeError, TypeError) as exc:    # never blocks the open
            debug.event("session", "starter snippets not read", error=str(exc))
            return 0
        return self.add_shipped(_STARTER_MARK, records, pages, category_model)

    @staticmethod
    def _preview_key(asset):
        """The preview key from the code text and language, so an edit makes a new key."""
        return ("code", asset.mat_id, hash(asset.code), asset.renderer)

    def painted_preview(self, row: int):
        """The code itself, painted when the snippet has no capture."""
        asset = self._assets[row]
        return self._preview_key(asset), functools.partial(self._paint_preview, asset)

    def preview_image(self, row: int):
        """The painted code, for the Customize preview."""
        return self._paint_preview(self._assets[row]) if 0 <= row < len(self._assets) else None

    def _paint_preview(self, asset) -> QtGui.QImage:
        return paint_code_preview(asset.code)
