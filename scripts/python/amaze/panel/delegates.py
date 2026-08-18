"""The item delegates: how a tile and a sidebar row are PAINTED - pure Qt reading roles off whatever model is attached, which is why every role arrives as a constructor argument rather than through an import, and why one delegate serves every section."""

import os

from PySide6 import QtCore, QtGui, QtWidgets

from amaze.core import category, debug
from amaze.helpers import theme, ui_helpers


QtGui.QPixmapCache.setCacheLimit(65536)   # APP-WIDE, for the whole of Houdini, which is why it is set once here and not in `__init__` - that runs one per section and again on every reload; 64MB covers a full screen of scaled tiles several times over

TOP_LEFT = "top-left"
TOP_RIGHT = "top-right"
LOWER_LEFT = "lower-left"
LOWER_RIGHT = "lower-right"


class Badge:
    """One tile badge as DATA - art, corner, and the delegate attribute holding its role - so `_paint_badges` is the only code that draws one and a section cannot lose a badge to silence."""

    __slots__ = ("name", "art", "corner", "role_attr", "minimum",
                 "hover_art")

    def __init__(self, name, art, corner, role_attr, minimum=0,
                 hover_art="") -> None:
        self.name = name
        self.art = art
        self.corner = corner
        self.role_attr = role_attr    # the delegate attribute holding this badge's role, or None where the section does not have it
        self.minimum = minimum        # a count badge draws only at or above this - versions is the only one, because an asset with a single version has no history to show
        self.hover_art = hover_art    # the second state, for the one badge that is a BUTTON

    def __repr__(self) -> str:                                # pragma: no cover
        return "<Badge %s>" % (self.name,)


BADGES = (      # THE TABLE, in paint order; no two share a corner, and the art lives in `ui/badge_*.svg` with the palette in the ART rather than in code - all four render AS DRAWN, no re-tinting
    Badge("open", "badge_open", TOP_LEFT, "_open_role"),                 # the scene currently open
    Badge("favourite", "badge_star", TOP_RIGHT, "_favorite_role"),       # favourite
    Badge("versions", "badge_versions", LOWER_LEFT, "_versions_role",
          minimum=2, hover_art="badge_versions_hover"),                  # more than one version
    Badge("comment", "badge_comment", LOWER_RIGHT, "_notes_role"),       # carries a comment
)


def role_color(index, role):
    """The QColor a row carries on `role`, or None for no role, no value, or a value QColor cannot read - so a caller paints only what it can paint and a damaged colour string is ignored rather than drawn as black."""
    if role is None:
        return None
    value = index.data(role)
    if not value:
        return None
    color = QtGui.QColor(str(value))
    return color if color.isValid() else None


class GridCellDelegate(QtWidgets.QStyledItemDelegate):
    """Every cell of the Grid's TABLE, and deliberately nothing else: the panel applies `hou.qt.styleSheet()` to its own root and every child inherits Houdini's item rules, so the table wears the host's selection band rather than a second opinion about it. ▸r/pluto-theme"""

    pass    # NO CELL PADDING, and the emptiness is the point: a `QTableView::item` stylesheet hands item drawing to `QStyleSheetStyle` and takes the font and every colour with it; a `QProxyStyle` on `PM_FocusFrameHMargin` via `setStyle` bus-errored at teardown (measured 2026-08-04); and insetting `option.rect` in `paint` shrinks the CELL, so the selection band stopped short at every column edge


class TickCellDelegate(GridCellDelegate):
    """A yes/no cell: a tick, or nothing. The mark is DRAWN rather than typed, so it needs no font and survives a machine whose fallback font lacks the glyph."""

    def __init__(self, source_delegate, role, colour, parent=None):
        super().__init__(parent)
        self._tiles = source_delegate
        self._role = role
        self._colour = colour

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.text = ""    # no TEXT: `DisplayRole` still carries the raw yes/no because the SORT compares it, and this is cleared HERE rather than in `paint`, which re-runs `initStyleOption` on its own copy and would put the word back

    SIDE = theme.ui_px(12)    # the mark's own side, and the air around it - a tick column is this wide and no wider, see `sizeHint`
    PAD = theme.ui_px(5)

    def _box(self, rect):
        """The tick's square at the cell's LEFT edge, where every other column and its own heading start - centring it (tried, reverted 2026-08-04) made the two mark columns read as a different table from the eight beside them."""
        side = max(min(rect.height() - theme.ui_px(6), self.SIDE), 1)
        return QtCore.QRect(rect.left() + self.PAD, rect.top(),
                            side, rect.height())

    def sizeHint(self, option, index):
        return QtCore.QSize(self.SIDE + 2 * self.PAD,           # as wide as the MARK, not as wide as the value behind it: the base measures `DisplayRole`, which still carries a word this cell never draws. Under `ResizeToContents` the heading still wins (measured: heading 80px, this hint 22px), so this states how wide the drawing is rather than deciding a width
                            super().sizeHint(option, index).height())

    def paint(self, painter, option, index):
        super().paint(painter, option, index)   # THE CELL first - selection band, alternating colour, hover, and no text because `initStyleOption` emptied it. Painting only the mark left a selected row's highlight stopping dead at this column and starting again after it
        if self._role is None:
            return
        if not index.siblingAtColumn(0).data(self._role):
            return
        self._tiles._paint_tick(
            painter, self._box(option.rect), self._colour)


class CategoryCellDelegate(GridCellDelegate):
    """The category column's INK - the two facts the model is not in a position to know: a selected row has ONE ink (a `ForegroundRole` otherwise outranks the selected-text colour and sits in its own colour on the highlight), and a dark colour on a dark row is not readable, so the raw value goes through the tiles' contrast rule against the palette's actual base."""

    def __init__(self, tiles, parent=None):
        super().__init__(parent)
        self._tiles = tiles

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        if option.state & QtWidgets.QStyle.StateFlag.State_Selected:
            return      # a selected row has ONE ink, and the base already set it
        raw = index.data(QtCore.Qt.ItemDataRole.ForegroundRole)
        if raw is None:
            return
        option.palette.setBrush(
            QtGui.QPalette.ColorRole.Text,
            QtGui.QBrush(self._tiles.readable_on(
                QtGui.QColor(raw), option.palette.base().color())))


class AssetItemDelegate(QtWidgets.QStyledItemDelegate):
    """Paints one grid tile or list row as thumbnail + name line + greyed subtitle, generic over which role feeds the subtitle so every section reuses it unchanged; any failure falls back to the default painting, so a bad row degrades to a plain name rather than breaking the view."""

    PAD = theme.ui_px(4)
    GAP = theme.ui_px(8)
    TEXT_COLOR = QtGui.QColor("#cdc8bc")
    DIM = QtGui.QColor("#5d7abd")    # the accent DEFAULT only: `setup()`/`show_prefs()` overwrite it per instance from `prefs.accent_color`, so the subtitle line tracks the accent preference live instead of drifting each time the accent moves
    THUMB_BG_COLOR = theme.color("surface_low")    # the dark ground behind the thumbnail area, so a non-square image still shows a tile boundary instead of blending into the panel. Its OWN constant: it was tied to `ClickSlider.RIGHT_COLOR` once, and tuning the slider silently recoloured every tile

    GRID_NAME_COLOR = theme.color("text")           # GRID tiles are quieter than list mode - the name in the neutral grey the design system already uses for unselected tabs
    GRID_SUBTITLE_COLOR = theme.color("text_dim")   # and the subtitle a dimmer grey rather than the accent, which list mode keeps
    GRID_TEXT_INSET = theme.ui_px(5)
    GRID_BOTTOM_PAD = theme.ui_px(5)      # text to card bottom: 16R, the same as the margins between cards, expressed as 5c because the spec measures the GLYPH bottom and the font descent (~5R) sits inside the QRect
    GRID_IMG_TEXT_GAP = theme.ui_px(8)    # image bottom to text top; `grid_cell_size` sizes the cell to this exact layout, so there is no leftover slack making tiles read tall

    CATEGORY_COLOR = QtGui.QColor("#d8d6d4")    # list mode's Category column where the category carries no colour of its own - a fixed yellow competing with the user's choice says the wrong thing about which one means something
    LIST_INK = QtGui.QColor("#d8d6d4")          # LIST MODE'S ONE INK: a table is read down its columns, so everything paints in this except Category, which paints in its own category's colour
    SELECTED_TEXT = QtGui.QColor("#000000")     # selection turns EVERY column black - the palette's highlightedText was not reliably dark against the amber highlight

    _badge_cache = {}    # rendered badge per (art, size, dpr) - every tile badge comes through here, one SVG rasterisation each for the whole app
    _font_cache = {}     # (family, pointsize, selected) -> (name_font, rend_font, fm, fm)

    @classmethod
    def grid_cell_size(cls, ts, base_font):
        """The grid cell (`gridSize`) matching `_paint`'s square layout: a width-filling square image, the image-to-text gap, both text lines and the bottom pad - sizing the cell to the layout is what keeps tiles tight instead of a small image adrift in a tall block."""
        pad = cls.PAD
        width = ts + theme.ui_px(10)
        icon_side = max(width - 2 * pad, 1)
        _nf, _rf, fm_name, fm_rend = cls.fonts_for(base_font, False)
        block_h = fm_name.height() + fm_rend.height()
        height = (
            pad
            + icon_side
            + cls.GRID_IMG_TEXT_GAP
            + block_h
            + cls.GRID_BOTTOM_PAD
        )
        return QtCore.QSize(width, height)

    BAND_TEXT_DARK = QtGui.QColor("#262626")     # text on a coloured band, not the palette's greys: those are tuned for the dark card, and a category colour can be any lightness at all
    BAND_TEXT_LIGHT = QtGui.QColor("#f0eeee")

    @staticmethod
    def _relative_luminance(color):
        """WCAG relative luminance - the sRGB-linearised one the contrast formula is defined against, not Rec. 601's perceptual approximation."""
        channels = []
        for value in (color.red(), color.green(), color.blue()):
            channel = value / 255.0
            channels.append(
                channel / 12.92 if channel <= 0.03928
                else ((channel + 0.055) / 1.055) ** 2.4
            )
        return (0.2126 * channels[0] + 0.7152 * channels[1]
                + 0.0722 * channels[2])

    @classmethod
    def contrast_ratio(cls, one, two):
        """WCAG contrast ratio between two colours (1.0 - 21.0)."""
        first = cls._relative_luminance(one)
        second = cls._relative_luminance(two)
        lighter, darker = max(first, second), min(first, second)
        return (lighter + 0.05) / (darker + 0.05)

    @classmethod
    def text_on(cls, background):
        """Whichever of the two band inks reads better on this colour, chosen by MEASURED contrast: a Rec. 601 threshold put the cut inside the green ramp and 8.7% of the RGB cube landed below 3:1, worst 1.54:1, where measuring has no bad case (worst 3.62:1) and moves none of the four shipped presets."""
        if cls.contrast_ratio(background, cls.BAND_TEXT_DARK) >= \
                cls.contrast_ratio(background, cls.BAND_TEXT_LIGHT):
            return cls.BAND_TEXT_DARK
        return cls.BAND_TEXT_LIGHT

    @classmethod
    def readable_on(cls, color, background, floor=4.5):
        """The colour lightened or darkened just enough to be legible on `background`, hue kept so it still identifies the category - for LIST mode, where the category is drawn as coloured TEXT on the row rather than as a filled band, and a dark category colour measured 1.03:1 against the row while reading fine in grid mode."""
        if cls.contrast_ratio(color, background) >= floor:
            return color
        toward_light = cls._relative_luminance(background) < 0.5   # walk lightness AWAY from the background until it clears
        best = color
        for _step in range(20):
            best = best.lighter(115) if toward_light else best.darker(115)
            if cls.contrast_ratio(best, background) >= floor:
                return best
        return cls.CATEGORY_COLOR    # saturated colours can hit the ceiling before the floor - pure blue never gets bright enough - so fall back to the neutral

    def _band_color(self, index):
        """The category colour for this row, or None to leave the card as it is; invalid values are ignored rather than painted."""
        return role_color(index, self._category_color_role)

    @classmethod
    def fonts_for(cls, option_font, selected):
        """Cached `(name_font, subtitle_font, name_metrics, subtitle_metrics)` for an option font and selection state - building fonts and metrics per row per repaint is measurable churn while scrolling, and nothing here is mutated after creation (`painter.setFont` copies), so the sidebar delegate shares the cache safely."""
        key = (option_font.family(), option_font.pointSizeF(), selected)
        cached = cls._font_cache.get(key)
        if cached is None:
            name_font = QtGui.QFont(option_font)
            rend_font = QtGui.QFont(option_font)
            name_font.setBold(True)    # the NAME is what you are looking for and the type under it is context, so bold separates them by WEIGHT and the two lines keep one baseline rhythm
            rend_font.setPointSizeF(name_font.pointSizeF())    # the sub-line reads as secondary through the grey COLOUR, never by size - it DERIVES the name's size, because an absolute 12pt floor here against a 9pt name drew a subtitle LARGER than the thing it describes wherever Houdini's UI font is small (measured on Windows 2026-08-04); the panel already floors its own font, and two independent floors agreeing by coincidence was the whole defect
            if selected:
                name_font.setBold(True)    # black-on-yellow reads too thin at regular weight, so bold everything on the highlight
                rend_font.setBold(True)
            cached = (
                name_font,
                rend_font,
                QtGui.QFontMetrics(name_font),
                QtGui.QFontMetrics(rend_font),
            )
            cls._font_cache[key] = cached
        return cached

    def __init__(
        self, subtitle_role, parent=None, category_role=None,
        favorite_role=None, tag_role=None, licence_role=None,
        open_role=None, crop_role=None,
        category_color_role=None,
        versions_role=None,
        notes_role=None,
        active_version_role=None,
    ):
        """Every role is optional and None means the delegate simply does not paint that thing, which is how one delegate serves sections that answer different questions."""
        super().__init__(parent)
        self._favorite_role = favorite_role    # the amber star badge, drawn LIVE from this role in every section; it replaced a material-only mechanism that baked a star into the cached thumbnail and never visibly worked
        self._open_role = open_role            # File section only: badges the tile of the scene currently open. None everywhere else, so no other section pays for it
        self._versions_role = versions_role    # Materials only today: the badge for an asset with more than one version
        self._active_version_role = active_version_role    # the active version's NAME, for list mode's Version column - the count above answers whether there are versions, this answers which one you are looking at
        self._notes_role = notes_role          # the comment badge in the tile's last free corner
        self._crop_role = crop_role            # a PER-ROW crop decision: a truthy value fills the tile and crops rather than letterboxing, so a File row's wide viewport capture fills its tile while image and geometry rows in the same view letterbox. None = never crop
        self._subtitle_role = subtitle_role
        self._category_role = category_role    # list mode's Category column source - the asset's category, the containing folder, or a palette's curated set. None = the column stays empty
        self._tag_role = tag_role              # list mode's last two columns; a section with neither passes None and simply does not get them
        self._licence_role = licence_role
        self._category_color_role = category_color_role    # a category can carry a colour, which paints the text band under the tile. None = this section has no category colours (folders and palette groups do not)

    @staticmethod
    def _to_pixmap(icon):
        """The model returns a QImage for the thumbnail (0 before it renders); normalise to a QPixmap for painting, or None when there is nothing."""
        if isinstance(icon, QtGui.QPixmap):
            return icon if not icon.isNull() else None
        if isinstance(icon, QtGui.QImage):
            if icon.isNull():
                return None
            return QtGui.QPixmap.fromImage(icon)
        if isinstance(icon, QtGui.QIcon):
            pm = icon.pixmap(256, 256)
            return pm if not pm.isNull() else None
        return None

    @staticmethod
    def _cover_pixmap(source, target, dpr, key):
        """Fill a square tile and CROP the overflow instead of letterboxing - a viewport capture is wide, so fitting it inside a square leaves dead bands and the image reads as small. Only rows that ask for it get this; everything else renders square thumbnails, where cover and contain are the same thing and the crop would be pure risk."""
        scaled = source.scaled(
            target,
            target,
            QtCore.Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        x = max(0, (scaled.width() - target) // 2)     # CENTRE-crop: an off-centre one would quietly cut the subject out of every wide capture
        y = max(0, (scaled.height() - target) // 2)
        cropped = scaled.copy(x, y, target, target)
        cropped.setDevicePixelRatio(dpr)
        QtGui.QPixmapCache.insert(key, cropped)
        return cropped

    @staticmethod
    def _icon_pixmap(icon, side, dpr=1.0, cover=False):
        """A scaled tile pixmap cached per (source image, target size, dpr), rendered at the display's PHYSICAL resolution with its ratio stamped so it paints crisp on Retina while callers still position it in logical units (▸`_logical_size`); without the cache every visible tile smooth-scales again on EVERY repaint, and scrolling repaints the viewport continuously."""
        target = max(1, round(side * dpr))
        if isinstance(icon, QtGui.QImage) and not icon.isNull():
            key = "assetlib_%s_%s_%s_%s" % (      # `cacheKey()` is stable for the stored, never-mutated thumbnails, so hits survive across paints - and a re-rendered thumbnail is a new QImage with a new key, so a stale tile cannot be served
                icon.cacheKey(), side, dpr, cover)
            cached = QtGui.QPixmapCache.find(key)
            if cached is not None and not cached.isNull():
                return cached
            if cover:
                return AssetItemDelegate._cover_pixmap(
                    QtGui.QPixmap.fromImage(icon), target, dpr, key)
            scaled = QtGui.QPixmap.fromImage(icon).scaled(
                target,
                target,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
            scaled.setDevicePixelRatio(dpr)
            QtGui.QPixmapCache.insert(key, scaled)
            return scaled
        pixmap = AssetItemDelegate._to_pixmap(icon)
        if pixmap is None:
            return None
        key = "assetlib_pm_%s_%s_%s_%s" % (     # CACHED TOO: only the QImage branch was, so a QPixmap or QIcon decoration smooth-scaled on every repaint of every visible tile. Latent today - every section delivers QImage through the engine - but the penalty is the cold-vs-warm gap measured on the other branch, 22.60ms against 8.58 for a 60-tile grid at ts=256
            pixmap.cacheKey(), side, dpr, cover)
        cached = QtGui.QPixmapCache.find(key)
        if cached is not None and not cached.isNull():
            return cached
        if cover:
            return AssetItemDelegate._cover_pixmap(pixmap, target, dpr, key)
        scaled = pixmap.scaled(
            target,
            target,
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(dpr)
        QtGui.QPixmapCache.insert(key, scaled)
        return scaled

    @staticmethod
    def _logical_size(pixmap):
        """Device-independent (logical) w, h of a possibly-Retina pixmap - what the centring maths must use, since `width()`/`height()` return PHYSICAL pixels once `devicePixelRatio` is set."""
        r = pixmap.devicePixelRatio() or 1.0
        return round(pixmap.width() / r), round(pixmap.height() / r)

    @classmethod
    def _badge_pixmap(cls, name, side, dpr=1.0):
        """One tile badge at DEVICE resolution, cached per (art, size, dpr) - AS DRAWN, with no colour substitution, because the art's own disc-and-stroke palette IS the design."""
        key = (name, side, round(dpr, 3))
        pixmap = cls._badge_cache.get(key)
        if pixmap is None:
            path = ui_helpers.ui_asset(name + ".svg")
            if os.path.exists(path):
                pixmap = ui_helpers.device_pixmap(path, side, dpr)
            else:
                pixmap = QtGui.QPixmap()    # a NULL pixmap, never a sized transparent one, or a missing badge paints a blank square over the thumbnail
            cls._badge_cache[key] = pixmap
        return pixmap

    @classmethod
    def _badge_side(cls, icon_side):
        """ONE size rule for all four corners: grow with the tile up to a cap, with a floor so LIST mode's small icons still get a legible mark."""
        return max(theme.ui_px(12), min(icon_side // 4, theme.ui_px(22)))

    FAV_MARK_COLOR = LIST_INK      # the mark columns' ink - the table's one colour, like every other list column
    OPEN_MARK_COLOR = LIST_INK
    NOTE_MARK_COLOR = LIST_INK

    @staticmethod
    def _paint_tick(painter, rect, color):
        """A tick, DRAWN rather than typed: U+2713 is missing from several fonts Houdini may fall back to, and a missing glyph is an empty box in a column whose entire job is to be a yes."""
        side = min(rect.width(), rect.height())
        if side < 4:
            return
        scale = side / 44.0    # the badge art's own check in its 44-unit box (M 34 14.94 L 18.88 30.06 L 12 23.19), kept in proportion so the drawn tick and the SVG one are the same shape
        cx = rect.center().x() - side / 2.0
        cy = rect.center().y() - side / 2.0
        path = QtGui.QPainterPath()
        path.moveTo(cx + 34 * scale, cy + 14.94 * scale)
        path.lineTo(cx + 18.88 * scale, cy + 30.06 * scale)
        path.lineTo(cx + 12 * scale, cy + 23.19 * scale)
        pen = QtGui.QPen(color, max(1.4, side * 0.09))
        pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
        painter.save()
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.restore()

    _versions_click = None    # set by the panel: called with the clicked index when the badge is hit. The delegate DETECTS; dialogs are the panel's

    def set_versions_click(self, callback) -> None:
        self._versions_click = callback

    def set_versions_hover(self, index) -> bool:
        """Remember which tile's versions badge the cursor is over and answer whether that CHANGED, so the caller repaints only then - a repaint per mouse move across a 500-tile grid is not free. Stored as a persistent index, because rows move under filtering and renaming and a stale row number would light the wrong tile."""
        current = getattr(self, "_versions_hover", None)
        new = QtCore.QPersistentModelIndex(index) if (
            index is not None and index.isValid()) else None
        if (current is None) != (new is None) or (
                new is not None and current is not None
                and QtCore.QModelIndex(current) != QtCore.QModelIndex(new)):
            self._versions_hover = new
            return True
        return False

    def _is_versions_hovered(self, index) -> bool:
        hover = getattr(self, "_versions_hover", None)
        return (hover is not None and hover.isValid()
                and QtCore.QModelIndex(hover) == index)

    def _is_list(self, option) -> bool:
        """IS THIS A LIST ROW? One question asked one way - it was asked three (the view's `viewMode()`, `option.decorationPosition`, and `prefs.view_mode`), nothing kept them in step, and the click was the one that drifted: it fired in list mode over a badge that mode never draws."""
        try:
            return (option.widget.viewMode()
                    == QtWidgets.QListView.ViewMode.ListMode)
        except Exception:                                # noqa: BLE001
            return False

    def versions_badge_at(self, index, option_rect, point, mode_grid):
        """Is `point` on this tile's versions badge? False below two versions, because there is no badge to be on and a tooltip over empty pixels is a lie."""
        if not mode_grid:
            return False    # A LIST ROW HAS NO BADGES - they became columns there, because at list size a badge is 12px and its art rasterises to a dark smudge; so there is nothing to hover, tooltip or click
        if self._versions_role is None or not index.isValid():
            return False
        count = index.data(self._versions_role)
        if not count or int(count) < 2:
            return False
        return self._versions_badge_rect(
            option_rect, mode_grid).contains(point)

    def _versions_badge_rect(self, option_rect, mode_grid):
        """Where the badge sits, for hit-testing - it MIRRORS the paint maths, and a few pixels of drift is tolerable on a 35px target."""
        pad = self.PAD
        icon_side = option_rect.width() - 2 * pad if mode_grid \
            else max(option_rect.height() - 2 * pad, 1)
        badge = self._badge_side(icon_side)
        inset = theme.ui_px(2)
        x = option_rect.left() + pad + inset
        y = option_rect.top() + pad + icon_side - badge - inset
        return QtCore.QRect(int(x), int(y), int(badge), int(badge))

    def helpEvent(self, event, view, option, index):
        """The versions badge names itself on hover and the rest of the tile stays silent; Qt asks the delegate first, so this is the hook - a tooltip set on the ITEM would follow the cursor across the whole tile."""
        if (event is not None
                and event.type() == QtCore.QEvent.Type.ToolTip
                and self.versions_badge_at(
                    index, option.rect, event.pos(),
                    not self._is_list(option))):
            QtWidgets.QToolTip.showText(
                event.globalPos(),
                ui_helpers.tooltip_text("Click to select version"),
                view)
            return True
        QtWidgets.QToolTip.hideText()
        return super().helpEvent(event, view, option, index)

    def editorEvent(self, event, model, option, index):
        """The one interactive spot on a tile: a click inside the versions badge, on an asset that has versions."""
        if (self._versions_click is not None
                and self._versions_role is not None
                and event.type() == QtCore.QEvent.Type.MouseButtonRelease
                and event.button() == QtCore.Qt.MouseButton.LeftButton):
            if self.versions_badge_at(
                    index, option.rect, event.position().toPoint(),
                    not self._is_list(option)):
                try:
                    self._versions_click(index)
                except Exception as exc:                  # noqa: BLE001
                    debug.event("versions", "badge click handler "
                                "failed", error=str(exc))
                return True
        return super().editorEvent(event, model, option, index)

    def badges(self) -> tuple:
        """Which badges this delegate actually shows, by name - DERIVED from the wired roles rather than declared a second time, so a delegate cannot claim a badge it cannot read. Which badges a SECTION ought to have is a different question, asked by `test_panel_correctness` against every section's model."""
        return tuple(badge.name for badge in BADGES
                     if getattr(self, badge.role_attr) is not None)

    def _paint_badges(self, painter, index, area_x, area_y,
                      icon_side, dpr=1.0):
        """Every badge this tile carries, in ONE pass over the table - the corners mean top-left open scene, top-right favourite, lower-left versions, lower-right comment."""
        side = self._badge_side(icon_side)
        inset = theme.ui_px(2)
        for badge in BADGES:
            role = getattr(self, badge.role_attr)
            if role is None:
                continue
            value = index.data(role)
            if not value:
                continue
            if badge.minimum and int(value) < badge.minimum:
                continue
            art = badge.art
            if badge.hover_art and self._is_versions_hovered(index):
                art = badge.hover_art    # the hover art is the SAME mark on a lighter disc - a button that answers the pointer. Only the versions badge has a second state; the others are indicators, not controls
            mark = self._badge_pixmap(art, side, dpr)
            if mark.isNull():
                continue
            mark_w, mark_h = self._logical_size(mark)    # LOGICAL size: `width()` is PHYSICAL pixels once the ratio is stamped, which would push a badge off the tile on a Retina display
            x = (area_x + inset if badge.corner in (TOP_LEFT, LOWER_LEFT)
                 else int(area_x + icon_side - mark_w - inset))
            y = (area_y + inset if badge.corner in (TOP_LEFT, TOP_RIGHT)
                 else int(area_y + icon_side - mark_h - inset))
            painter.drawPixmap(x, y, mark)

    def sizeHint(self, option, index):
        """Mirror the `gridSize` the view was given, exactly, so layout and paint rect always agree - without this Qt falls back to a heuristic partly keyed on whether `DecorationRole` currently holds an icon, and a section whose thumbnail arrives late paints a tiny image adrift in a mostly empty tile."""
        try:
            grid = option.widget.gridSize()
            if grid.isValid() and grid.height() > 0:
                is_list = self._is_list(option)
                if is_list:
                    width = option.widget.viewport().width()
                    return QtCore.QSize(width if width > 0 else grid.width(), grid.height())
                if grid.width() > 0:
                    return grid
        except Exception:
            pass
        return super().sizeHint(option, index)

    def paint(self, painter, option, index):
        """The save/restore pair lives HERE, wrapped in a `finally`, and NOT at the top and bottom of `_paint`: Qt drives every visible item with ONE painter, so a row that raised in between skipped the restore and left the shared painter's save stack growing by one per failing tile. `_paint` reads all three of its model roles before it touches the painter - pinned by a test, because if a model read ever moves below the first `setPen` the imbalance becomes a real colour leak into every row after it."""
        try:
            painter.save()
            try:
                self._paint(painter, option, index)
            finally:
                painter.restore()
        except Exception:
            super().paint(painter, option, index)    # balanced again by the `finally` above, so the fallback paints on a clean painter

    def _paint(self, painter, option, index):
        """The tile itself: card, optional category band, thumbnail, badges, then the two text lines."""
        selected = bool(option.state & QtWidgets.QStyle.StateFlag.State_Selected)
        alternate = bool(
            option.features & QtWidgets.QStyleOptionViewItem.ViewItemFeature.Alternate
        )
        if selected:
            painter.fillRect(option.rect, option.palette.highlight())
        elif alternate:
            painter.fillRect(option.rect, option.palette.alternateBase())

        rect = option.rect
        icon = index.data(QtCore.Qt.ItemDataRole.DecorationRole)
        name = index.data(QtCore.Qt.ItemDataRole.DisplayRole) or ""
        renderer = index.data(self._subtitle_role) or ""

        try:
            dpr = option.widget.devicePixelRatioF()    # tile images render at the display's PHYSICAL resolution, or sharp-edged content like the code preview is visibly upscaled on Retina
        except Exception:
            dpr = 1.0

        name_font, rend_font, fm_name, fm_rend = self.fonts_for(
            option.font, selected
        )
        h_name = fm_name.height()
        h_rend = fm_rend.height()

        raw_category = self._band_color(index)    # resolved ONCE - a full proxy-to-source round trip plus a QColor parse, and the grid used to ask again for its band: measured 120 reads for 60 tiles, 0.31ms of every 8.57ms repaint, with the first result discarded

        pad = self.PAD
        text_x = rect.left() + pad + self.GRID_TEXT_INSET
        text_w = max(rect.width() - 2 * pad - self.GRID_TEXT_INSET, 1)
        block_h = h_name + h_rend    # the FULL two-line block whether or not there is a subtitle: `grid_cell_size` always reserves both, so sizing the card from the DRAWN text left a tile with no renderer label 18px shorter than its own cell, card and colour band both stopping short over bare grid background
        name_dy = 0 if renderer else h_rend // 2    # a single line is then centred in the block it fills, rather than clinging to the top of it
        icon_side = max(rect.width() - 2 * pad, 1)
        icon_x = rect.left() + pad
        icon_y = rect.top() + pad
        text_top = icon_y + icon_side + self.GRID_IMG_TEXT_GAP
        card_bottom = text_top + block_h + self.GRID_BOTTOM_PAD    # the dark backing covers the WHOLE tile, image area and text block alike, down to the card's bottom edge - one continuous card, with both gaps at 16R so it reads square rather than tall
        painter.fillRect(
            QtCore.QRect(
                icon_x, icon_y, icon_side, card_bottom - icon_y
            ),
            self.THUMB_BG_COLOR,
        )
        band_color = raw_category    # the band under the image takes its CATEGORY's colour where one is set, painted OVER the card rather than instead of it, so the image area is untouched and an uncoloured category costs nothing
        if band_color is not None and not selected:
            band_top = icon_y + icon_side
            painter.fillRect(
                QtCore.QRect(
                    icon_x, band_top, icon_side,
                    max(card_bottom - band_top, 0),
                ),
                band_color,
            )
        if selected:
            zone_top = icon_y + icon_side    # the card fill just covered the highlight the base pass painted; restore it on the TEXT zone only, so a selected tile keeps its yellow band and black text with the thumbnail intact
            painter.fillRect(
                QtCore.QRect(
                    icon_x,
                    zone_top,
                    icon_side,
                    max(card_bottom - zone_top, 0),
                ),
                option.palette.highlight(),
            )
        scaled = self._icon_pixmap(
            icon, icon_side, dpr,
            self._crop_role is not None
            and bool(index.data(self._crop_role))) if icon else None
        if scaled is not None:
            lw, _ = self._logical_size(scaled)
            ix = rect.left() + (rect.width() - lw) // 2
            painter.drawPixmap(ix, icon_y, scaled)
        self._paint_badges(painter, index, icon_x, icon_y, icon_side, dpr)
        painter.setFont(name_font)
        name_pen = self.SELECTED_TEXT if selected else self.GRID_NAME_COLOR
        subtitle_pen = None
        if band_color is not None and not selected:
            name_pen = self.text_on(band_color)    # a user-chosen colour can be any lightness and the normal text is pale, so both lines flip together and the pair stays readable
            subtitle_pen = name_pen
        painter.setPen(name_pen)
        painter.drawText(
            QtCore.QRect(text_x, text_top + name_dy, text_w, h_name),
            QtCore.Qt.AlignmentFlag.AlignLeft
            | QtCore.Qt.AlignmentFlag.AlignVCenter,
            fm_name.elidedText(
                name, QtCore.Qt.TextElideMode.ElideRight, text_w
            ),
        )
        if renderer:
            painter.setFont(rend_font)
            painter.setPen(
                subtitle_pen if subtitle_pen is not None
                else (self.SELECTED_TEXT if selected
                      else self.GRID_SUBTITLE_COLOR)
            )
            painter.drawText(
                QtCore.QRect(text_x, text_top + h_name, text_w, h_rend),
                QtCore.Qt.AlignmentFlag.AlignLeft
                | QtCore.Qt.AlignmentFlag.AlignVCenter,
                fm_rend.elidedText(
                    renderer, QtCore.Qt.TextElideMode.ElideRight, text_w
                ),
            )


class SidebarItemDelegate(QtWidgets.QStyledItemDelegate):
    """Paints the category/folder sidebar's rows - name, entry count, and the colour bar down a coloured category's left edge - by DECLARING them in `initStyleOption` and letting the host's style draw the row, which is what keeps its selection, hover and alternating colour identical to the Grid table's."""

    PAD = theme.ui_px(6)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.show_counts = True    # counts on individual categories can be toggled off in Preferences; All always shows its total
        self.drag_row = -1         # row highlighted while an asset is dragged over it, -1 for none
        self._drag_color = QtGui.QColor(AssetItemDelegate.DIM)
        self.color_role = None     # role carrying a category's colour, or None for sidebars that have none (folders, palette groups)

    def set_drag_color(self, color: QtGui.QColor) -> None:
        self._drag_color = QtGui.QColor(color)

    def _swatch_color(self, index):
        """This row's category colour, or None; invalid values are ignored rather than painted."""
        return role_color(index, self.color_role)

    BAR = theme.ui_px(4)    # the colour bar's width. EVERY row reserves it - a coloured category fills it, a plain one leaves it transparent - so all labels start at the same x; indenting only the coloured rows sat neighbouring labels 4px apart

    def initStyleOption(self, option, index):
        """Everything the STYLE needs to draw the row itself, set up as ordinary view-item fields so nothing is painted by hand; `option.text` is DISPLAY ONLY and never touches `DisplayRole`, which stays the clean name because category matching, restore-by-text and the filters all key off it."""
        super().initStyleOption(option, index)
        name = str(index.data(QtCore.Qt.ItemDataRole.DisplayRole) or "")
        count = index.data(category.SIDEBAR_COUNT_ROLE)
        if not self.show_counts and name != "All":
            count = None
        if count is not None:
            option.text = "%s (%s)" % (name, count)
        if option.state & QtWidgets.QStyle.StateFlag.State_Selected:
            font = QtGui.QFont(option.font)
            font.setBold(True)
            option.font = font
        side = max(QtGui.QFontMetrics(option.font).height(), 1)    # FROM THE FONT, never from `option.rect`: that rect is not the row here - Qt passes a much larger one when asking for a size hint - so deriving the decoration from it grew the row's hint until one selected row filled the whole sidebar with its band
        pixmap = QtGui.QPixmap(self.BAR, side)
        swatch = self._swatch_color(index)
        pixmap.fill(swatch if swatch is not None
                    else QtGui.QColor(0, 0, 0, 0))
        option.icon = QtGui.QIcon(pixmap)    # the bar is a DECORATION rather than an inset rect, because Qt lays the text out after a decoration on its own, where insetting `option.rect` would shrink the CELL and cut the band short at the row's edge
        option.decorationSize = QtCore.QSize(self.BAR, side)
        option.features |= (
            QtWidgets.QStyleOptionViewItem.ViewItemFeature.HasDecoration)
        if index.row() == self.drag_row:
            option.backgroundBrush = QtGui.QBrush(self._drag_color)    # drop-target feedback through the option the style READS, rather than a fill painted over the top of what it drew
