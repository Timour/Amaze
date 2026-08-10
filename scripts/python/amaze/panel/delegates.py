"""The item delegates: how a tile and a sidebar row are PAINTED.

Both are pure Qt - they read roles off whatever model is attached and
draw. They were 610 lines inside panel.py, which is the panel's single
largest block of code that has nothing to do with the panel's
behaviour; moving them out is code motion only, verified by hashing
the pixels of 48 rendered tiles before and after.

AssetItemDelegate is shared by EVERY section (materials, textures,
colors, cop, geometry, code) in both grid and list mode - the roles it
reads are passed in per section, which is why it takes them as
constructor arguments rather than importing a model.
"""

import collections
import os

from PySide6 import QtCore, QtGui, QtWidgets

from amaze.core import category, debug
from amaze.helpers import theme, ui_helpers
from amaze.prefs import prefs


# Scaled tiles are cached (see AssetItemDelegate._icon_pixmap) - 64MB
# covers a full screen of tiles at any slider size several times over.
#
# Set ONCE, here, not in __init__: this raises Qt's APP-WIDE pixmap
# budget for the whole of Houdini, and __init__ runs five times per
# panel (one delegate per section) plus again on every reload.
QtGui.QPixmapCache.setCacheLimit(65536)

#: The four tile badges are ONE drawn family (design call 2026-08-01,
#: replacing four accreted looks that were hard to read on busy
#: thumbnails): each glyph sits on its own dark disc, so it reads on
#: ANY thumbnail, and all four render AS DRAWN - no re-tinting, no
#: per-badge colour coding. The art:
#:   ui/badge_open.svg      top-left     scene currently open (check)
#:   ui/badge_star.svg      top-right    favourite (star outline)
#:   ui/badge_versions.svg  lower-left   has versions (stacked lines)
#:   ui/badge_comment.svg   lower-right  carries a comment
#: One size rule for all four: _badge_side, the star's old proportional
#: rule adopted family-wide.

TOP_LEFT = "top-left"
TOP_RIGHT = "top-right"
LOWER_LEFT = "lower-left"
LOWER_RIGHT = "lower-right"


class Badge:
    """One tile badge, as DATA (2026-08-05).

    The ART and the paint path became one family on 2026-08-01 - one
    size rule, one pixmap cache, four SVGs. What stayed four was the
    CODE: `_paint_open_badge`, `_paint_versions_badge`,
    `_paint_notes_badge` and `_paint_favorite_badge` each re-decided the
    size, the inset, the corner arithmetic and the null-pixmap guard,
    and each opened with its own `if role is None: return`. A section
    that should have carried a badge and did not got silence - no
    badge, no error, no way to notice.

    A badge is a row here now, and `_paint_badges` is the only code that
    draws one. Which SECTIONS carry which is a separate question, asked
    where it can be answered honestly: a test walks each section's model
    and fails when the model can answer a badge's role and the section's
    delegate does not wire it.
    """

    __slots__ = ("name", "art", "corner", "role_attr", "minimum",
                 "hover_art")

    def __init__(self, name, art, corner, role_attr, minimum=0,
                 hover_art="") -> None:
        self.name = name
        self.art = art
        self.corner = corner
        #: The delegate attribute holding this badge's role, or None
        #: when the section does not have it.
        self.role_attr = role_attr
        #: A count badge draws only at or above this. Versions is the
        #: only one: an asset with a single version has no history to
        #: show, so the badge means "there is more than one".
        self.minimum = minimum
        #: The second state, for the one badge that is a BUTTON.
        self.hover_art = hover_art

    def __repr__(self) -> str:                                # pragma: no cover
        return "<Badge %s>" % (self.name,)


#: THE TABLE. Order is paint order, which is also the order the corners
#: were assigned; no two share a corner, so it does not matter visually
#: and a reader can check the family against the art list above.
BADGES = (
    Badge("open", "badge_open", TOP_LEFT, "_open_role"),
    Badge("favourite", "badge_star", TOP_RIGHT, "_favorite_role"),
    Badge("versions", "badge_versions", LOWER_LEFT, "_versions_role",
          minimum=2, hover_art="badge_versions_hover"),
    Badge("comment", "badge_comment", LOWER_RIGHT, "_notes_role"),
)


def role_color(index, role):
    """The QColor a row carries on `role`, or None.

    None for no role, no value, or a value QColor cannot read - so a
    caller paints only what it can actually paint, and a damaged
    colour string is ignored rather than drawn as black.

    ONE reader. The tile delegate's `_band_color` and the sidebar's
    `_swatch_color` were the same ten lines with the role held under a
    different attribute name.
    """
    if role is None:
        return None
    value = index.data(role)
    if not value:
        return None
    color = QtGui.QColor(str(value))
    return color if color.isValid() else None


class GridCellDelegate(QtWidgets.QStyledItemDelegate):
    """Every cell of the Grid's TABLE: the air either side of its text,
    and nothing else.

    **THE SELECTION IS HOUDINI'S.** The panel applies
    `hou.qt.styleSheet()` to its own root and every child inherits it,
    so the table already gets Houdini's item rules:

        QAbstractItemView::item:selected {
            color:      rgb(@TextColor@);
            background: rgb(@ListEntrySelected:BlendColor=ListEntry2,
                            BlendBias=0.77@);
        }
        QTableView::item:selected { border-top/bottom: 1px
            solid rgb(@ListEntrySelected@); }

    `ListEntrySelected` is `SELECTION_BASE` (HSV 40 0.825 0.725) and
    `TextColor` is `TEXT` (grey 0.8) - both from `config/UIDark.hcs`.
    So the band is that yellow blended toward the row with the full
    colour as a hairline top and bottom, which is what every other list
    in Houdini looks like.

    This class used to fill its own band and clear `State_Selected` so
    the style could not paint one. That is gone: the list wears the
    host's selection rather than a second opinion about it.
    """

    #: NO CELL PADDING HERE, and that is the whole point of the class
    #: now being empty. Three routes were tried and each cost more than
    #: five pixels is worth:
    #:
    #: * a `QTableView::item` stylesheet - wins, but hands item drawing
    #:   to `QStyleSheetStyle`, which takes the font and every colour
    #:   with it;
    #: * a `QProxyStyle` on `PM_FocusFrameHMargin` via `setStyle` - the
    #:   view does not own the style and the bindings keep no reference
    #:   to it, and the process bus-errored at teardown (2026-08-04,
    #:   measured: three test classes went fatal, and a live session
    #:   left a signal-10 crash log in HOUDINI_TEMP_DIR on quit);
    #: * insetting `option.rect` in `paint` - shrinks the CELL, not the
    #:   text, so the selection band stopped short at every column edge.
    #:   `test_a_tick_cell_PAINTS_ITSELF_when_the_row_is_selected`
    #:   caught it, which is the bug it was written for.
    #:
    #: What is left is Houdini's own item metrics, like every other
    #: list in the application.
    pass


class TickCellDelegate(GridCellDelegate):
    """A yes/no cell: a tick, or nothing.

    A column of the word "false" is a wall of text that says nothing -
    the 2026-08-01 decision, kept. The tick is DRAWN, not typed, so it
    needs no font (which is also why it survived a machine with no
    suitable glyph).
    """

    def __init__(self, source_delegate, role, colour, parent=None):
        super().__init__(parent)
        self._tiles = source_delegate
        self._role = role
        self._colour = colour

    def initStyleOption(self, option, index):
        """No TEXT. The display role still carries the raw yes/no,
        because the SORT compares it - but the cell draws a mark, and
        a column of the word "False" was the 2026-08-01 decision this
        replaced. Cleared HERE and not before `paint`, because
        `QStyledItemDelegate.paint` re-runs `initStyleOption` on its
        own copy and would put the word back."""
        super().initStyleOption(option, index)
        option.text = ""

    #: The mark's own side, and the air around it. A tick column is
    #: this wide and no wider - see `sizeHint`.
    SIDE = theme.ui_px(12)
    PAD = theme.ui_px(5)

    def _box(self, rect):
        """The tick's square, at the cell's LEFT edge - where every
        other column starts, and where its own heading starts.

        It was centred for one build, on the reasoning that a mark has
        no reading order to line up with, and reverted after seeing it
        live (2026-08-04). A `QHeaderView` label is left-aligned, so a
        centred mark hangs in the middle of a column whose heading
        starts at the edge - the two columns read as a different table
        from the eight beside them.
        """
        side = max(min(rect.height() - theme.ui_px(6), self.SIDE), 1)
        return QtCore.QRect(rect.left() + self.PAD, rect.top(),
                            side, rect.height())

    def sizeHint(self, option, index):
        """As wide as the MARK, not as wide as the value behind it.

        The base class measures `DisplayRole`, and that role still
        carries the raw yes/no because the sort compares it - so it
        asks for room to print a word this cell never draws.

        This does NOT decide the column's width on its own: under
        `ResizeToContents` a column is the larger of its heading and
        its cells, and for a tick column the heading wins (measured
        2026-08-04: heading 80px, this hint 22px). It is here because
        a delegate should say how wide its own drawing is, not because
        it changed a width.
        """
        return QtCore.QSize(self.SIDE + 2 * self.PAD,
                            super().sizeHint(option, index).height())

    def paint(self, painter, option, index):
        # THE CELL, then the mark. The base draws the row - selection
        # band, alternating colour, hover - and no text, because
        # `initStyleOption` above emptied it. This painted only the
        # mark once, and a selected row's highlight stopped dead at
        # Favorite and started again after it (seen in the panel,
        # 2026-08-04).
        super().paint(painter, option, index)
        if self._role is None:
            return
        if not index.siblingAtColumn(0).data(self._role):
            return
        self._tiles._paint_tick(
            painter, self._box(option.rect), self._colour)


class CategoryCellDelegate(GridCellDelegate):
    """The category column's INK - the two things the model cannot know.

    The model answers `ForegroundRole` with the raw colour the user
    gave that category, which is honest data and all it is in a
    position to say. Two facts belong to the VIEW:

    * **A selected row has ONE ink.** Every other column goes dark on
      the selection band; the category did not - a `ForegroundRole`
      outranks the selected-text colour - and sat there in its own
      colour on the highlight. Reported 2026-08-04. Black for every
      column of a selected row is what the painted list did
      (`SELECTED_TEXT if selected`) before this.
    * **A dark colour on a dark row is not readable.** #333333 measures
      1.03:1 against the row while reading fine two views over, where
      the grid FILLS a band with it rather than writing in it. The pass
      is the tiles' own, against the palette's actual base and not a
      literal, because the panel follows the theme.

    `initStyleOption` and nothing else - no paint code, no text
    drawing. Qt draws the cell; this only says what colour it is.
    """

    def __init__(self, tiles, parent=None):
        super().__init__(parent)
        self._tiles = tiles

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        if option.state & QtWidgets.QStyle.StateFlag.State_Selected:
            # A selected row has ONE ink, and the base already set it.
            return
        raw = index.data(QtCore.Qt.ItemDataRole.ForegroundRole)
        if raw is None:
            return
        option.palette.setBrush(
            QtGui.QPalette.ColorRole.Text,
            QtGui.QBrush(self._tiles.readable_on(
                QtGui.QColor(raw), option.palette.base().color())))


class AssetItemDelegate(QtWidgets.QStyledItemDelegate):
    """Paints each grid/list tile as thumbnail + name line + a greyed
    subtitle line beneath it (renderer for materials, file format for
    textures, etc.), in both grid (icon on top, text below) and list (icon
    left, text right) modes. Any failure falls back to the default painting
    so a bad case degrades to a plain name rather than breaking the view.
    Generic over which role feeds the subtitle line, so it's reused as-is
    for every section (Materials/Textures/...), not just materials."""

    PAD = theme.ui_px(4)
    GAP = theme.ui_px(8)
    TEXT_COLOR = QtGui.QColor("#cdc8bc")
    # Class value = the accent DEFAULT; setup()/show_prefs() overwrite
    # it per-instance from prefs.accent_color so the subtitle line
    # tracks the accent preference live (it was deliberately matched to
    # the accent in the H21 color pass, then drifted every time the
    # accent changed - now it follows).
    DIM = QtGui.QColor("#5d7abd")
    # Confirmed keeper (started as a "TEST"; its color has since been
    # tuned, settling that it stays): dark background behind
    # the thumbnail area, so a non-square image (e.g. a wide HDR
    # panorama) still shows a visible tile boundary instead of blending
    # into the panel background.
    # Own constant, not tied to ClickSlider.RIGHT_COLOR - it briefly was,
    # which meant the later slider-specific color tuning (a request for
    # a slider-only "right side dark color") silently recolored
    # every thumbnail tile's background too, an unintended side effect
    # nobody asked for.
    THUMB_BG_COLOR = theme.color("surface_low")

    # GRID tiles only (the asset103-vs-104 annotated design shot):
    # quieter text than list mode - name in the neutral grey the design
    # system already uses for unselected tabs, subtitle a dimmer grey
    # instead of the accent.
    # The text block sits 10R (5c) in from the tile's LEFT edge and is
    # ANCHORED TO THE CELL BOTTOM with 10R padding ("10px padding from
    # the bottom, not to the picture") - its position is independent of
    # where the thumbnail ends. The ~16R measured to the next row
    # emerges from bottom padding + the next cell's own top pad. List
    # mode keeps TEXT_COLOR/DIM untouched (Type column stays accent).
    GRID_NAME_COLOR = theme.color("text")
    GRID_SUBTITLE_COLOR = theme.color("text_dim")
    GRID_TEXT_INSET = theme.ui_px(5)
    # Text-to-card-bottom padding: 16R, same as the margins between
    # cards (the simplified spec). 5c by QRect - the spec's measurements
    # read the GLYPH bottom, which sits the font descent (~5R) inside
    # the QRect, so 10R + descent lands the visible gap at ~16R.
    GRID_BOTTOM_PAD = theme.ui_px(5)
    # Image-bottom -> text-top gap. The tile is now "square": the image
    # fills the tile width, the text sits GRID_IMG_TEXT_GAP below it and
    # GRID_BOTTOM_PAD above the card's bottom edge (spec: 16px to the
    # image, 16px to the edge). grid_cell_size() sizes the cell to match
    # so there's no leftover slack making tiles read tall.
    GRID_IMG_TEXT_GAP = theme.ui_px(8)

    # List mode's Category column text. A very light grey by default,
    # because a category can now carry a COLOUR of its own - and a
    # fixed yellow competing with the user's choice says the wrong
    # thing about which one means something. Coloured categories paint
    # this column in their own colour instead (see _band_color); the
    # grey is what "no colour set" looks like.
    CATEGORY_COLOR = QtGui.QColor("#d8d6d4")
    #: LIST MODE'S ONE INK. Everything in the table paints in this
    #: except Category, which paints in its own category's colour.
    LIST_INK = QtGui.QColor("#d8d6d4")
    # The per-column colours - Tags amber, License blue, Type green -
    # went with the painted list they belonged to (`ListColumnHeader`
    # and `ListColumns` retired with the QTableView migration). Nothing
    # read them afterwards: LIST_INK above is the one ink now, and the
    # comment they carried still told the reader to keep them in step
    # with a class that no longer exists.
    # Selected rows/tiles paint ALL text black (the accent/
    # yellow columns were hard to read against the amber selection
    # highlight; the palette's highlightedText wasn't reliably dark).
    SELECTED_TEXT = QtGui.QColor("#000000")

    #: rendered badge per (art, size, dpr) - every tile badge comes
    #: through here, one SVG rasterization each for the whole app
    _badge_cache = {}
    #: (family, pointsize, selected) -> (name_font, rend_font, fm, fm)
    _font_cache = {}

    @classmethod
    def grid_cell_size(cls, ts, base_font):
        """The grid cell (gridSize) matching _paint's square layout:
        width = ts + 10, height = top pad + a width-filling square image
        + the 16R image->text gap + the two text lines + the 16R bottom
        pad. Sizing the cell to the layout is what keeps tiles tight/
        square instead of a small image adrift in a tall block."""
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

    #: Text on a coloured band. Not the palette's greys: those are
    #: tuned for the dark card, and a category colour can be any
    #: lightness at all.
    BAND_TEXT_DARK = QtGui.QColor("#262626")
    BAND_TEXT_LIGHT = QtGui.QColor("#f0eeee")

    @staticmethod
    def _relative_luminance(color):
        """WCAG relative luminance - the sRGB-linearised one the
        contrast formula is defined against, not Rec. 601's perceptual
        approximation."""
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
        """Whichever of the two inks reads better on this band.

        Was a Rec. 601 luminance threshold at 140, which put the cut
        just inside the green ramp: #00ee00 measures 139.7 and so took
        the LIGHT ink, giving near-white on bright green at 1.37:1.
        Swept the RGB cube - 8.7% of colours landed below 3:1, worst
        1.54:1.

        Choosing by measured contrast instead is the same amount of
        code and has no bad case: worst 3.62:1, nothing below 3:1. It
        also changes NOTHING for the four shipped presets - Salmon,
        Mint, Sky and Sand measure identically under both rules
        (6.10, 10.45, 8.02, 7.65) - so this only rescues custom
        colours."""
        if cls.contrast_ratio(background, cls.BAND_TEXT_DARK) >= \
                cls.contrast_ratio(background, cls.BAND_TEXT_LIGHT):
            return cls.BAND_TEXT_DARK
        return cls.BAND_TEXT_LIGHT

    @classmethod
    def readable_on(cls, color, background, floor=4.5):
        """The colour, lightened or darkened just enough to be legible
        on `background` - hue kept, so it still identifies the category.

        For the LIST view, where the category is drawn as coloured TEXT
        on the row rather than as a filled band. The raw user colour
        went straight to the pen there with no contrast rule at all, so
        a dark category colour was invisible against the #313131 row
        while reading fine in grid mode: #333333 measured 1.03:1,
        #262626 1.16:1, #000000 1.61:1 - the opposite of the two views
        agreeing, which is what the colour feature is for."""
        if cls.contrast_ratio(color, background) >= floor:
            return color
        # Walk lightness away from the background until it clears.
        toward_light = cls._relative_luminance(background) < 0.5
        best = color
        for _step in range(20):
            best = best.lighter(115) if toward_light else best.darker(115)
            if cls.contrast_ratio(best, background) >= floor:
                return best
        # Saturated colours can hit the ceiling before the floor (pure
        # blue never gets bright enough): fall back to the neutral.
        return cls.CATEGORY_COLOR

    def _band_color(self, index):
        """The category colour for this row, or None to leave the card
        as it is. Invalid values are ignored rather than painted."""
        return role_color(index, self._category_color_role)

    @classmethod
    def fonts_for(cls, option_font, selected):
        """Cached (name_font, subtitle_font, name_metrics,
        subtitle_metrics) for an option font + selection state.
        Building fonts and metrics per row per repaint is measurable
        churn while scrolling, and the option font only changes with
        Houdini's UI scale - the cache holds a couple of entries for
        the app's whole life. Never mutated after creation
        (painter.setFont copies), so sharing is safe. The sidebar
        delegate shares this cache."""
        key = (option_font.family(), option_font.pointSizeF(), selected)
        cached = cls._font_cache.get(key)
        if cached is None:
            name_font = QtGui.QFont(option_font)
            rend_font = QtGui.QFont(option_font)
            # The NAME is the thing you are looking for; the type under
            # it is context. Bold separates them by weight rather than
            # by size, so the two lines still share a baseline rhythm.
            name_font.setBold(True)
            # Sub-line reads as secondary via the grey COLOUR, not by
            # being a different size: it is the name's size, full stop.
            #
            # It used to be `max(option_font.pointSizeF(), 12.0)` - an
            # ABSOLUTE floor, against a name drawn at the option font's
            # own size. Measured 2026-08-04: with Houdini's UI font at
            # 9pt (Windows) and a view that did not inherit the panel's
            # own floored font, that gives a 9pt name under a 12pt
            # subtitle - the subtitle LARGER than the thing it
            # describes, on every tile and every list row. macOS never
            # showed it because the UI font here is ~13pt and the floor
            # never engages.
            #
            # The panel already floors ITS font (panel.py). Two
            # independent floors that agree only by coincidence is the
            # whole defect; this one derives instead of deciding.
            rend_font.setPointSizeF(name_font.pointSizeF())
            if selected:
                # Black-on-yellow reads too thin at regular weight
                # - bold everything on the highlight.
                name_font.setBold(True)
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
        super().__init__(parent)
        # Favorited tiles get a small amber star badge drawn LIVE from
        # this role - uniformly across every section. Replaces the old
        # material-only mechanism that baked a star into the cached
        # thumbnail image, which never visibly worked in this panel's
        # whole life (the feature went unnoticed until a review
        # mentioned it).
        self._favorite_role = favorite_role
        # File section only: badges the tile of the scene currently
        # open. None everywhere else, so no other section pays for it.
        self._open_role = open_role
        # Materials only today: the chevrons badge for an asset with
        # more than one version. None everywhere else.
        self._versions_role = versions_role
        # The active version's NAME, for list mode's Version column.
        # The count above answers "are there versions"; this answers
        # "which one am I looking at", which only a row has room for.
        self._active_version_role = active_version_role
        # Asset sections and File: the note badge in the tile's last
        # free corner. None = no badge.
        self._notes_role = notes_role
        # PER-ROW crop decision (was a whole-view flag when HIP had its
        # own delegate): a truthy value in this role fills the tile and
        # crops rather than letterboxing - hip rows' wide viewport
        # captures - while the same view letterboxes its image and
        # geometry rows. None = never crop.
        self._crop_role = crop_role
        self._subtitle_role = subtitle_role
        # List mode's Category column source (materials/cop: the
        # categories list; textures: the containing folder; gradients:
        # user category or curated set). None = column stays empty.
        self._category_role = category_role
        # List mode's last two columns. Sections that have neither
        # (textures, geometry) pass None and simply do not get them -
        # the panel pushes a width of 0 and the header skips the label.
        self._tag_role = tag_role
        self._licence_role = licence_role
        #: A category can carry a colour, which paints the text band
        #: under the tile. None = this section has no category colours
        #: (folders and palette groups do not).
        self._category_color_role = category_color_role
        # List-mode spreadsheet columns (Thumbnail | Name | Type |
        # Category), pushed in by the panel's _update_list_columns() -
        # the Name column is sized to the longest currently-visible name.
    @staticmethod
    def _to_pixmap(icon):
        """The model returns a QImage for the thumbnail (0 before it renders);
        normalise to a QPixmap for painting, or None if there's nothing."""
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
        """Fill a square tile and CROP the overflow, instead of
        letterboxing.

        A scene capture is the viewport's shape - wide - so fitting it
        inside a square tile leaves dead bands above and below and the
        image reads as small. Filling the tile's height and cropping
        left/right shows the middle of the frame at full size, which is
        where the subject is.

        Only the HIP section asks for this. Everything else renders
        square thumbnails, where cover and contain are the same thing
        and the crop would be pure risk.
        """
        scaled = source.scaled(
            target,
            target,
            QtCore.Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        # Centre-crop: an off-centre crop would quietly cut the subject
        # out of every wide capture.
        x = max(0, (scaled.width() - target) // 2)
        y = max(0, (scaled.height() - target) // 2)
        cropped = scaled.copy(x, y, target, target)
        cropped.setDevicePixelRatio(dpr)
        QtGui.QPixmapCache.insert(key, cropped)
        return cropped

    @staticmethod
    def _icon_pixmap(icon, side, dpr=1.0, cover=False):
        """Scaled tile pixmap, cached per (source image, target size, dpr)
        in QPixmapCache - without this, every visible tile smooth-scales
        its image again on EVERY repaint (scrolling repaints the whole
        viewport continuously). QImage.cacheKey() is stable for the
        stored, never-mutated thumbnails, so cache hits survive across
        paints; a rerendered thumbnail is a new QImage with a new key,
        so stale tiles can't be served. The pixmap is rendered at the
        display's PHYSICAL resolution (side * dpr) with its devicePixel-
        Ratio set, so drawPixmap paints it crisp on Retina rather than
        upscaling a logical-size pixmap 2x - the callers still position
        it in logical units (see _logical_size)."""
        target = max(1, round(side * dpr))
        if isinstance(icon, QtGui.QImage) and not icon.isNull():
            key = "assetlib_%s_%s_%s_%s" % (
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
        # CACHED TOO. Only the QImage branch above was, so a QPixmap or
        # QIcon decoration smooth-scaled on every repaint of every
        # visible tile - the exact cost the QImage branch exists to
        # avoid. Latent today (every section delivers QImage through the
        # engine), but the penalty is the cold-vs-warm gap already
        # measured on the other branch: 22.60ms against 8.58 for a
        # 60-tile grid repaint at ts=256, and 40.74 against 15.80 in
        # list mode at ts=512.
        key = "assetlib_pm_%s_%s_%s_%s" % (
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
        """Device-independent (logical) w, h of a (possibly Retina)
        pixmap - what the centering math must use, since width()/height()
        return physical pixels once devicePixelRatio is set."""
        r = pixmap.devicePixelRatio() or 1.0
        return round(pixmap.width() / r), round(pixmap.height() / r)

    @classmethod
    def _badge_pixmap(cls, name, side, dpr=1.0):
        """One tile badge (see the family table at module top), at
        DEVICE resolution: rasterised at side*dpr with the ratio
        stamped, or the mark is soft on top of thumbnails that
        _icon_pixmap renders sharp - the star's old Retina lesson,
        inherited by the whole family. AS DRAWN: no colour
        substitution; the art's own disc-and-stroke palette IS the
        design."""
        key = (name, side, round(dpr, 3))
        pixmap = cls._badge_cache.get(key)
        if pixmap is None:
            path = ui_helpers.ui_asset(name + ".svg")
            if os.path.exists(path):
                pixmap = ui_helpers.render_svg_pixmap(
                    path, max(1, round(side * dpr))
                )
                pixmap.setDevicePixelRatio(dpr)
            else:
                pixmap = QtGui.QPixmap()
            cls._badge_cache[key] = pixmap
        return pixmap

    @classmethod
    def _badge_side(cls, icon_side):
        """ONE size rule for all four corners - the star's old
        proportional rule adopted family-wide (2026-08-01): grow with
        the tile up to a cap, with a floor so LIST mode's small icons
        still get a legible mark."""
        return max(theme.ui_px(12), min(icon_side // 4, theme.ui_px(22)))

    #: The mark columns' ink - the table's one colour, like every
    #: other list column. (VERSION_COLOR sat here too and was read by
    #: nothing; the Version column paints in LIST_INK like the rest.)
    FAV_MARK_COLOR = LIST_INK
    OPEN_MARK_COLOR = LIST_INK
    NOTE_MARK_COLOR = LIST_INK
    #: "none" is the same ink as everything else. It briefly had its
    #: own dimmer grey; one ink for the table means one ink.

    @staticmethod
    def _paint_tick(painter, rect, color):
        """A tick, DRAWN - not the character.

        U+2713 is missing from several fonts Houdini may fall back to,
        and a missing glyph is an empty box in a column whose entire
        job is to be a yes. Two lines cannot go missing, and they are
        the same check the open badge draws, so the column and the
        badge are visibly the same mark.
        """
        side = min(rect.width(), rect.height())
        if side < 4:
            return
        # The badge art's own check, in its 44-unit box:
        # M 34 14.94 L 18.88 30.06 L 12 23.19 - kept in proportion so
        # the drawn tick and the SVG one have the same shape.
        scale = side / 44.0
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

    #: Set by the panel: called with the clicked index when the badge
    #: is hit. The delegate detects; dialogs are the panel's.
    _versions_click = None

    def set_versions_click(self, callback) -> None:
        self._versions_click = callback

    def set_versions_hover(self, index) -> bool:
        """Remember which tile's versions badge the cursor is over.

        The badge is the one BUTTON on a tile, so it is the one thing
        that answers the pointer (2026-08-01). Returns whether the
        answer changed, so the caller repaints only then - a repaint
        per mouse move across a 500-tile grid is not free.

        Stored as a persistent index: rows move under filtering and
        renaming, and a stale row number would light the wrong tile."""
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
        """IS THIS A LIST ROW? One question, asked one way.

        It was asked three ways: paint and sizeHint read the view's
        `viewMode()`, the badge hit-tests read
        `option.decorationPosition`, and the panel's hover sync read
        `prefs.view_mode`. Nothing kept the three in step, and the
        click was the one that drifted - it fired in list mode, over a
        badge that mode never draws.
        """
        try:
            return (option.widget.viewMode()
                    == QtWidgets.QListView.ViewMode.ListMode)
        except Exception:                                # noqa: BLE001
            return False

    def versions_badge_at(self, index, option_rect, point, mode_grid):
        """Is `point` on this tile's versions badge? False when the
        asset has fewer than two versions - there is no badge to be
        on, and a tooltip over empty pixels is a lie."""
        # A LIST ROW HAS NO BADGES. They became columns there on
        # 2026-08-01, because at list size a badge is 12px and its art
        # rasterises to a dark smudge - so there is nothing to hover,
        # nothing to tooltip and nothing to click.
        if not mode_grid:
            return False
        if self._versions_role is None or not index.isValid():
            return False
        count = index.data(self._versions_role)
        if not count or int(count) < 2:
            return False
        return self._versions_badge_rect(
            option_rect, mode_grid).contains(point)

    def _versions_badge_rect(self, option_rect, mode_grid):
        """Where the badge sits, for hit-testing - mirrors the paint
        maths; a few pixels of drift is tolerable on a 35px target."""
        pad = self.PAD
        icon_side = option_rect.width() - 2 * pad if mode_grid \
            else max(option_rect.height() - 2 * pad, 1)
        badge = self._badge_side(icon_side)
        inset = theme.ui_px(2)
        x = option_rect.left() + pad + inset
        y = option_rect.top() + pad + icon_side - badge - inset
        return QtCore.QRect(int(x), int(y), int(badge), int(badge))

    def helpEvent(self, event, view, option, index):
        """The versions badge names itself on hover; the rest of the
        tile stays silent. Qt asks the delegate first, so this is the
        hook - no tooltip is set on the item, which would follow the
        cursor across the whole tile."""
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
        """The one interactive spot on a tile: a click inside the
        versions badge, on an asset that has versions."""
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
        """Which badges this delegate actually shows, by name.

        Derived from the wired roles rather than declared a second time:
        one source of truth, so a delegate cannot claim a badge it
        cannot read. What each SECTION ought to have is a different
        question, and it is asked by a test - `test_panel_correctness`
        walks every section's model and fails when a model can answer a
        badge's role and its delegate does not wire it. That is the half
        that used to be invisible: a missing role painted nothing, with
        no error and no way to notice.
        """
        return tuple(badge.name for badge in BADGES
                     if getattr(self, badge.role_attr) is not None)

    def _paint_badges(self, painter, index, area_x, area_y,
                      icon_side, dpr=1.0):
        """Every badge this tile carries, in ONE pass over the table.

        Four near-identical painters lived here - each re-deciding the
        size, the inset, the corner arithmetic and the null-pixmap
        guard, and each with its own `if role is None: return`. The
        corners mean: top-left open scene, top-right favourite,
        lower-left versions, lower-right comment.
        """
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
            # The hover art is the SAME mark on a lighter disc (50% vs
            # 75% black) - a button that answers the pointer, per the
            # design. Only the versions badge has a second state; the
            # others are indicators, not controls.
            if badge.hover_art and self._is_versions_hovered(index):
                art = badge.hover_art
            mark = self._badge_pixmap(art, side, dpr)
            if mark.isNull():
                continue
            # LOGICAL size: width() is PHYSICAL pixels once
            # devicePixelRatio is set, which would push a badge off the
            # tile on a Retina display. This was right in the star's
            # painter and approximated in the other three.
            mark_w, mark_h = self._logical_size(mark)
            x = (area_x + inset if badge.corner in (TOP_LEFT, LOWER_LEFT)
                 else int(area_x + icon_side - mark_w - inset))
            y = (area_y + inset if badge.corner in (TOP_LEFT, TOP_RIGHT)
                 else int(area_y + icon_side - mark_h - inset))
            painter.drawPixmap(x, y, mark)

    def sizeHint(self, option, index):
        """Without this override, Qt falls back to its own heuristic (partly
        based on whether DecorationRole currently has an icon), independent
        of the gridSize apply_view_mode() sets on the view - the delegate
        then paints correctly inside whatever (possibly much smaller) rect
        Qt handed it, which looks like a tiny thumbnail floating in a mostly
        empty row/tile. Materials mostly hid this because a placeholder icon
        is always present immediately; textures return None until a
        thumbnail actually generates, exposing it. Mirror gridSize() (set in
        apply_view_mode()) exactly so layout and paint rect always agree."""
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
        # The save/restore pair lives HERE, wrapped in a finally, and NOT
        # at the top and bottom of _paint.
        #
        # Qt drives every visible item with ONE painter. _paint used to
        # save first and restore last, so a row that raised in between -
        # library.py's `self._assets[index.row()].name` has no bounds
        # check, and a row can vanish between layout and paint - skipped
        # the restore and left the shared painter with an unbalanced save
        # stack, growing by one per failing tile. Measured:
        # "QPainter::end: Painter ended with 1 saved states".
        #
        # Scope, checked rather than assumed: _paint reads all three of
        # its model roles (Decoration, Display, subtitle) BEFORE it
        # touches the painter, so a raising model cannot also leave a pen
        # or font behind - the imbalance is the whole of the damage
        # today. That ordering is now pinned by a test, because if a
        # model read ever moves below the first setPen, the leak becomes
        # real and every row after it repaints in the wrong colour.
        # SidebarItemDelegate.paint already got this right.
        try:
            painter.save()
            try:
                self._paint(painter, option, index)
            finally:
                painter.restore()
        except Exception:
            # Balanced again by the finally above, so the fallback paints
            # on a clean painter.
            super().paint(painter, option, index)

    def _paint(self, painter, option, index):
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


        # Render tile images at the display's physical resolution so they
        # stay crisp on a Retina screen instead of being upscaled 2x when
        # painted (photos tolerate that, sharp-edged content like the code
        # preview does not).
        try:
            dpr = option.widget.devicePixelRatioF()
        except Exception:
            dpr = 1.0

        name_font, rend_font, fm_name, fm_rend = self.fonts_for(
            option.font, selected
        )
        h_name = fm_name.height()
        h_rend = fm_rend.height()

        # Selection turns EVERY column black - name, type and category
        # colors all fight the amber highlight otherwise.
        # ONE INK FOR THE WHOLE TABLE. Every list column paints in the
        # same light grey - name, type, tags, license, the three ticks
        # and the version - because a table is read down its columns,
        # and six colours across a row is decoration competing with
        # the one colour that MEANS something. Category is the
        # exception: it carries the colour the user gave that category,
        # which is the whole point of colouring a category.
        # ONE INK for every column but Category. There were four names
        # for this single expression - name_color, type_color,
        # tags_color, license_color - which is what the comment above
        # already says the design IS: one colour that means something
        # (the category's own) against one that does not compete with
        # it. A sabotage that painted the name in "the type colour"
        # went green because the two were the same value, which is how
        # four names for one thing announce themselves.
        #
        # `dim_color` was here too, assigned and never read - the grid
        # path builds its own.
        # THE CATEGORY'S OWN COLOUR, resolved ONCE - a full
        # proxy->source round trip plus a QColor parse. The grid used
        # to ask again for its band: measured 120 CategoryColorRole
        # reads for 60 grid tiles, costing 0.31ms of every 8.57ms
        # repaint, 3.6%, and the first result was discarded.
        raw_category = self._band_color(index)

        pad = self.PAD
        text_x = rect.left() + pad + self.GRID_TEXT_INSET
        text_w = max(rect.width() - 2 * pad - self.GRID_TEXT_INSET, 1)
        # The FULL two-line block, whether or not there is a
        # subtitle. grid_cell_size always reserves both lines, so
        # sizing the card from the drawn text made a tile with no
        # renderer label 18px shorter than its own cell - card and
        # colour band both stopping short, with bare grid background
        # underneath, right next to normal tiles. Measured at
        # ts=128: last painted row 179 with a subtitle, 161 without.
        # library.renderer_label returns "" for an unknown renderer,
        # so this is not rare.
        block_h = h_name + h_rend
        # The single line is then centred in the block it fills,
        # rather than clinging to the top of it.
        name_dy = 0 if renderer else h_rend // 2
        # "Square" tile: the image fills the tile width, the text
        # sits GRID_IMG_TEXT_GAP below it (not floating with leftover
        # slack, which read as too-tall tiles). grid_cell_size()
        # sizes the cell to this exact layout.
        icon_side = max(rect.width() - 2 * pad, 1)
        icon_x = rect.left() + pad
        icon_y = rect.top() + pad
        # The tile's dark backing covers the WHOLE tile - the image
        # area AND the text block below it, down to the cell's
        # bottom edge (per the red-marked 104 design shot: the grey
        # extends under the text, one continuous card).
        # Text top-anchored 16R below the image; the card ends
        # GRID_BOTTOM_PAD below the text. Both gaps are 16R, so the
        # card reads square/tight rather than a small image adrift
        # in a tall grey block.
        text_top = icon_y + icon_side + self.GRID_IMG_TEXT_GAP
        card_bottom = text_top + block_h + self.GRID_BOTTOM_PAD
        painter.fillRect(
            QtCore.QRect(
                icon_x, icon_y, icon_side, card_bottom - icon_y
            ),
            self.THUMB_BG_COLOR,
        )
        # The band under the image takes its CATEGORY's colour when
        # one is set - the card's own dark grey otherwise. Painted
        # over the card rather than instead of it, so the image area
        # is untouched and an uncoloured category costs nothing.
        # Resolved once, above. The RAW colour: the band is filled
        # with it and text_on picks an ink against it.
        band_color = raw_category
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
            # The card fill just covered the selection highlight the
            # base pass painted - restore it on the TEXT zone (below
            # the image), so a selected tile reads like it always
            # did: yellow band, black bold text, thumbnail intact.
            zone_top = icon_y + icon_side
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
            # A user-chosen colour can be any lightness, and the
            # normal text is pale - on a pale band it disappears.
            # Both lines flip together so the pair stays readable.
            name_pen = self.text_on(band_color)
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
    """Paints the category/folder sidebar's rows: the name, its entry
    count, and the colour bar down a coloured category's left edge.

    **THE SELECTION IS NOT ITS BUSINESS** (2026-08-04). It used to fill
    its own band, on the reasoning that Houdini's app-wide stylesheet
    outranks a widget palette so a palette change could never be seen.
    True, and the wrong conclusion: that stylesheet is the panel's own
    `hou.qt.styleSheet()` line, which every child inherits, so the band
    was already there and being painted over. `initStyleOption` empties
    the text and `paint` chains to the base for the CELL, which brings
    the host's selection, hover and alternating colour - then the name,
    count and swatch go on top. Same shape as `TickCellDelegate`.

    A stylesheet on `cat_list` ITSELF is still the wrong answer: it
    pushes Qt onto the CSS path for parts the sheet does not cover,
    its own scrollbar among them."""

    PAD = theme.ui_px(6)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Counts on individual categories can be toggled off in
        # Preferences; "All" always shows its total (fixed rule).
        self.show_counts = True
        # Row highlighted while an asset is dragged over it (drop target
        # feedback, in the accent/select purple). -1 = none.
        self.drag_row = -1
        self._drag_color = QtGui.QColor(AssetItemDelegate.DIM)
        #: Role carrying a category's colour, or None for sidebars that
        #: have none (folders, palette groups).
        self.color_role = None

    def set_drag_color(self, color: QtGui.QColor) -> None:
        self._drag_color = QtGui.QColor(color)

    def _swatch_color(self, index):
        """This row's category colour, or None. Invalid values are
        ignored rather than painted."""
        return role_color(index, self.color_role)

    #: The colour bar's width. EVERY row reserves it - a coloured
    #: category fills it, a plain one leaves it transparent - so all
    #: labels start at the same x. Indenting only the coloured rows sat
    #: neighbouring labels 4px apart.
    BAR = theme.ui_px(4)

    def initStyleOption(self, option, index):
        """Everything the STYLE needs, so it can draw the row itself.

        The name, the count suffix and the colour bar are set up here
        as ordinary view-item fields - text, font, decoration - and
        `QStyledItemDelegate.paint` then draws the row the way the host
        draws every other list: its band, its selected-text colour, its
        elision. Nothing is painted by hand.

        **`option.text` is DISPLAY ONLY.** It never touches the model's
        `DisplayRole`, which stays the clean name because category
        matching, restore-by-text and the filters all key off it.

        The bar is a DECORATION rather than an inset rect: Qt lays the
        text out after a decoration on its own, where insetting
        `option.rect` would shrink the CELL and cut the band short at
        the row's edge.
        """
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
        # FROM THE FONT, never from `option.rect`. That rect is not the
        # row here - Qt passes a much larger one when it is asking for
        # a size hint, so deriving the decoration from it made
        # `decorationSize` enormous, the row's hint grew to match, and
        # a single selected row filled the whole sidebar with its band.
        side = max(QtGui.QFontMetrics(option.font).height(), 1)
        pixmap = QtGui.QPixmap(self.BAR, side)
        swatch = self._swatch_color(index)
        pixmap.fill(swatch if swatch is not None
                    else QtGui.QColor(0, 0, 0, 0))
        option.icon = QtGui.QIcon(pixmap)
        option.decorationSize = QtCore.QSize(self.BAR, side)
        option.features |= (
            QtWidgets.QStyleOptionViewItem.ViewItemFeature.HasDecoration)
        if index.row() == self.drag_row:
            # Drop-target feedback through the option the style reads,
            # rather than a fill painted over the top of what it drew.
            option.backgroundBrush = QtGui.QBrush(self._drag_color)

    # NO `paint` OVERRIDE. Everything this row needs is declared in
    # `initStyleOption` above, so the base class - and through it the
    # host's style - draws the whole thing. What that buys, beyond the
    # selection colour: elision, hover, the alternating colour and the
    # focus rectangle all arrive without being reimplemented, and the
    # row cannot disagree with the Grid table about what a selected
    # row looks like, because neither of them decides any more.
