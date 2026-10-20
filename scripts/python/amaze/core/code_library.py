"""Models for the Code section - reusable code snippets (VEX wrangles, OpenCL kernels, Python SOP scripts): a material-style library over its own code.json, CodeLibrary/CodeCategories subclassing the material machinery. Storage is INLINE text, not a node archive - the snippet lives in the Material.code field, persisted through get_as_dict/from_dict like any other field, so code.json is fully self-contained and there are no <id>.mat/.png files at all. Thumbnails are PAINTED, not rendered: a monospace preview of the first lines of code via the unified engine's PAINT path (thumbnails.engine.deposit), keyed by the code's content so an edit mints a fresh preview. The renderer field holds the LANGUAGE ("VEX"/"OpenCL"/"Python"), which becomes the tile subtitle and the search/filter dimension. Import applies the code to a node's snippet parm (or copies it), instead of building a scene."""

import os
import json

import hou
from PySide6 import QtCore, QtGui

import amaze
from amaze import amazetheme
from amaze.core import debug, library, category, material, thumbnails, tile_icons
from amaze.helpers import hostos

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


def shelf_kwargs(name: str) -> dict:
    """The `kwargs` a shelf click gives its script, so shelf scripts run unchanged ▸r/shelf-kwargs."""
    held = QtGui.QGuiApplication.keyboardModifiers()
    keys = QtCore.Qt.KeyboardModifier
    mac = hostos.is_macos()
    ctrl, cmd = keys.ControlModifier, keys.MetaModifier
    if mac and not QtCore.QCoreApplication.testAttribute(
            QtCore.Qt.ApplicationAttribute.AA_MacDontSwapCtrlAndMeta):
        ctrl, cmd = cmd, ctrl    # on a Mac Qt names Command "Control" unless the app turns that off
    return {"pane": None, "viewport": None, "panename": "", "toolname": name,
            "shiftclick": bool(held & keys.ShiftModifier), "ctrlclick": bool(held & ctrl),
            "altclick": bool(held & keys.AltModifier), "cmdclick": mac and bool(held & cmd),
            "requestnew": True, "branch": False, "autoplace": False,
            "inputs": [], "inputnodename": "", "outputindex": -1,
            "outputs": [], "outputnodename": "", "inputindex": -1}


def run_python(name: str, code: str) -> str:
    """Run a Python snippet in this Houdini as one undo step: "" or its error's last line."""
    import traceback
    try:
        compiled = compile(str(code or ""), "<snippet %s>" % name, "exec")
    except SyntaxError as exc:
        return "line %s: %s" % (exc.lineno, exc.msg)
    try:
        with hou.undos.group("Run %s" % name):
            exec(compiled, {"__name__": "__main__", "hou": hou,    # noqa: S102
                            "kwargs": shelf_kwargs(name)})
    except (Exception, SystemExit):                          # noqa: BLE001
        traceback.print_exc()
        return traceback.format_exc().strip().splitlines()[-1]
    return ""


class CodeCategories(category.Categories):
    """The Code section's category sidebar - same model, own database."""

    DB_FILENAME = "code.json"


class CodeLibrary(library.AssetLibrary):
    """The Code section's asset model - the shared engine over code.json, storing snippet text inline and painting a preview."""

    NOTES_SECTION = "code"
    TILE_FACE = "face_code"    # T05

    DB_FILENAME = "code.json"

    CONTENT_SURVIVES_A_REFUSED_INDEX_WRITE = False  # snippets are stored INLINE, so a refused list write leaves nothing on disk to recover and Repair has nothing to put back - the message must say the snippet was not saved, rather than the base class's "the files are there"

    def cleanup_db(self, show_dialog: bool = True) -> int:
        """Deliberately reduced to a state flush: code snippets live INLINE in code.json - there are no <id>.mat/.interface/thumbnail files - so the inherited cleanup's missing-file and lonely-file passes would classify EVERY snippet as an orphan and delete the whole library."""
        self.save()
        self.last_cleanup_summary = [  # a LIST, matching the base contract - the panel joins the lines; a bare string would be joined character by character
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
    ) -> str:
        """Register a code snippet. Returns the language string on success (the renderer-string contract add_asset has), "" on failure (empty code)."""
        if not code.strip():
            return ""
        new_mat = material.Material()
        tags = self.sanitize_tags(tags)
        new_mat.set_data(
            name.strip() or "Snippet", cats, tags, fav, language or "Code"
        )
        new_mat.code = code
        self._append_record(new_mat)
        if not self.save():  # a snippet lives INLINE in code.json, so a refused write orphans no files - but the snippet the user just watched appear is not saved, and they have to be told
            self.report_refused_index_write(new_mat)
        return language or "Code"

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
        asset = self._assets[row]
        key_before = self._preview_key(asset)  # the OLD content's key, taken before the mutation - computed after, the discard targets the NEW key, a guaranteed miss, and the stale preview squats in the shared LRU
        asset.set_data(
            name.strip() or asset.name,
            cats,
            self.sanitize_tags(tags),
            asset.fav,
            language or "Code",
        )
        asset.code = code
        thumbnails.engine.discard(key_before)
        self.rebuild_thumbs()
        self._saved_rows_changed([asset])
        return True

    def row_data(self, row, role):
        """The tooltip is the snippet's own comment ▸p/d03-retired; the rest is the base's."""
        if role == QtCore.Qt.ItemDataRole.ToolTipRole:
            from amaze.core import notes
            from amaze.helpers import ui_helpers

            page = notes.note_for(
                self.preferences,
                notes.note_key(self.NOTES_SECTION,
                               str(self._assets[row].mat_id)))
            said = "\n".join(item.get("text", "")    # TEXT blocks only, never a to-do or a picture
                             for item in page.get("items", [])
                             if item.get("t") == "text").strip()
            return ui_helpers.tooltip_text(said) if said else None  # no name: the tile shows it
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
            with open(marker, "w", encoding="utf-8") as handle:  # written OUTSIDE the try that wraps the save, and even when nothing was added, so a broken or empty def file is not retried on every launch
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
        if tile_icons.face_for(self, row) != "preview":    # no thumbnail FILE to swap here
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

    def apply_to_node(self, row: int, node: hou.Node):
        """Set the snippet onto a node's code parm. Returns (ok, reason) so the panel can report a node with no code parm."""
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

    def import_asset_to_scene(self, index, target="auto", context_node=None):
        """Double-click applies the snippet to the selected node - a code snippet has no node archive to import. Returns (ok, reason, created) like every import; created is always empty here, since applying text creates nothing."""
        node = None
        sel = hou.selectedNodes()
        if len(sel) == 1:
            node = sel[0]
        ok, reason = self.apply_to_node(index.row(), node)
        return ok, reason, []

    def render_thumbnail(self, row) -> None:
        """No render - a code snippet has no thumbnail to render; repaint the preview from current content instead."""
        if 0 <= row < len(self._assets):
            thumbnails.engine.discard(
                self._preview_key(self._assets[row])
            )
            self.row_changed(row, [QtCore.Qt.ItemDataRole.DecorationRole])
