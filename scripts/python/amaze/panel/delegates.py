"""The item delegates that paint tiles and sidebar rows, every role passed in by the caller."""

import os

from PySide6 import QtCore, QtGui, QtWidgets

import amaze
from amaze import amazetheme
from amaze import tooltips
from amaze.core import category, debug, renderers
from amaze.helpers import theme, ui_helpers


QtGui.QPixmapCache.setCacheLimit(65536)   # 64MB, app-wide for all of Houdini; set once, here

class Badge:
    """One tile badge: its ID, the model role it reads, its click `handler`, its SVGs and tooltips."""

    __slots__ = ("name", "svg", "role", "role_attr", "handler", "minimum", "equals", "dims",
                 "hover_svg", "press_svg", "off_svg", "off_hover_svg", "tip", "off_tip")

    def __init__(self, name, svg, role="", role_attr="", handler="", minimum=0, equals="",
                 dims=False, hover_svg="", press_svg="", off_svg="", off_hover_svg="",
                 tip="", off_tip="") -> None:
        self.name = name
        self.svg = svg
        self.role = role              # the model role, by name, whose value decides if it is drawn; "" = always
        self.role_attr = role_attr    # the delegate attribute holding that role's number; list columns read it
        self.handler = handler        # the section method a click runs; "" = an indicator, not a button
        self.minimum = minimum        # drawn when the count is at least this: one version has no history
        self.equals = equals          # the role value this badge is drawn for; "" = any truthy value
        self.dims = dims              # its ON art's icon is drawn at the button opacities, rest and hover
        self.hover_svg = hover_svg    # a separate SVG for the hover state, where it has one
        self.press_svg = press_svg    # a separate SVG while the button is held down, where it has one
        self.off_svg = off_svg        # drawn while the role is falsy, its icon at the button opacities
        self.off_hover_svg = off_hover_svg    # the off state under the pointer, at full opacity
        self.tip = tip               # the tooltip text, from tooltips.py; "" = no tooltip
        self.off_tip = off_tip        # the tooltip in the off state, where a click does the opposite

    def is_on(self, value) -> bool:
        """Whether a truthy role value shows this badge's ON state, per `minimum` or `equals`."""
        if self.minimum:
            return int(value) >= self.minimum
        return not self.equals or value == self.equals

    def __repr__(self) -> str:                                # pragma: no cover
        return "<Badge %s>" % (self.name,)


BADGES = (      # in paint order; art in `ui/badge_*.svg`, one file each ▸r/tile-from-frame
    Badge("open", "badge_open", "OpenSceneRole", "_open_role"),    # the scene currently open
    Badge("favourite", "badge_favourite", "FavoriteRole", "_favorite_role", "menu_favourite",
          off_svg="badge_favourite_off",    # the on state is drawn as the SVG is, with no hover change
          off_hover_svg="badge_favourite_off_hover",
          tip=tooltips.BADGE_FAVORITE_REMOVE, off_tip=tooltips.BADGE_FAVORITE_ADD),
    Badge("versions", "badge_versions", "VersionsRole", "_versions_role", "menu_versions",
          minimum=2, dims=True, hover_svg="badge_versions_hover", tip=tooltips.BADGE_VERSIONS),
    Badge("comment", "badge_comment", "NotesRole", "_notes_role", "menu_comments",
          off_svg="badge_comment_off", off_hover_svg="badge_comment_off_hover",    # on is as drawn
          tip=tooltips.BADGE_COMMENTS),
    Badge("execute", "badge_execute", "RendererRole", "_execute_role", "menu_run",
          equals="Python", hover_svg="badge_execute_hover", press_svg="badge_execute_press",
          tip=tooltips.BADGE_EXECUTE),    # the language role: Run is for Python only
)
BADGE = {badge.name: badge for badge in BADGES}


def role_color(index, role):
    """The QColor a row carries on `role`, or None for no role, no value or an unreadable one."""
    if role is None:
        return None
    value = index.data(role)
    if not value:
        return None
    color = QtGui.QColor(str(value))
    return color if color.isValid() else None


def show_capped_tooltip(event, view, index) -> bool:
    """Show an item's tooltip at the pointer, width-capped; False when it has none."""
    if event is None or event.type() != QtCore.QEvent.Type.ToolTip:
        return False
    words = index.data(QtCore.Qt.ItemDataRole.ToolTipRole)
    if not words:
        return False
    QtWidgets.QToolTip.showText(event.globalPos(), ui_helpers.tooltip_text(str(words)), view)
    return True


def os_file_icon(path: str, side: int) -> QtGui.QImage:
    """The system's icon for `path`'s file type, centred on a transparent `side` square; never empty."""
    provider = QtWidgets.QFileIconProvider()
    icon = provider.icon(QtCore.QFileInfo(path))
    target = side // 2
    pixmap = icon.pixmap(target, target)
    if pixmap.isNull():
        style = QtWidgets.QApplication.style()
        if style is not None:
            pixmap = style.standardIcon(
                QtWidgets.QStyle.StandardPixmap.SP_FileIcon
            ).pixmap(target, target)
    image = QtGui.QImage(
        side, side,
        QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    if not pixmap.isNull():
        drawn = min(target, pixmap.width() * 2)    # a small native icon upscales at most 2x
        painter = QtGui.QPainter(image)
        painter.setRenderHint(
            QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        offset = (side - drawn) // 2
        painter.drawPixmap(
            QtCore.QRect(offset, offset, drawn, drawn), pixmap)
        painter.end()
    return image


class GridCellDelegate(QtWidgets.QStyledItemDelegate):
    """Every cell of the Grid's table, drawn by the host style, text at TEXT_INSET. ▸r/pluto-theme"""

    TEXT_INSET = theme.ui_px(amazetheme.drawn_list()["text_inset"])    # paint draws the cell, then its text here ▸r/list-from-frame

    @staticmethod
    def _style(widget):
        return widget.style() if widget is not None else QtWidgets.QApplication.style()

    @classmethod
    def text_margin(cls, widget) -> int:
        """Where the style starts a cell's text: its focus-frame margin plus one."""
        return cls._style(widget).pixelMetric(
            QtWidgets.QStyle.PixelMetric.PM_FocusFrameHMargin, None, widget) + 1

    def text_shift(self, widget) -> int:
        """How far right of the style's own text margin the text starts, to sit at TEXT_INSET."""
        return max(self.TEXT_INSET - self.text_margin(widget), 0)

    def paint(self, painter, option, index):
        cell = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(cell, index)
        extras = (QtWidgets.QStyleOptionViewItem.ViewItemFeature.HasDecoration
                  | QtWidgets.QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator)
        shift = self.text_shift(option.widget)
        if not shift or not cell.text or cell.features & extras:
            return super().paint(painter, option, index)
        style, text = self._style(option.widget), cell.text
        cell.text = ""
        style.drawControl(QtWidgets.QStyle.ControlElement.CE_ItemViewItem,
                          cell, painter, option.widget)
        cell.text = text
        cell.rect = option.rect.adjusted(shift, 0, 0, 0)
        cell.state &= ~QtWidgets.QStyle.StateFlag.State_HasFocus
        style.drawControl(QtWidgets.QStyle.ControlElement.CE_ItemViewItem,
                          cell, painter, option.widget)

    def helpEvent(self, event, view, option, index):
        """A cell's tooltip, width-capped by `show_capped_tooltip`, as on the tiles."""
        return (show_capped_tooltip(event, view, index)
                or super().helpEvent(event, view, option, index))


class TickCellDelegate(GridCellDelegate):
    """A yes/no cell: a drawn tick, or nothing."""

    def __init__(self, source_delegate, role, colour, parent=None):
        super().__init__(parent)
        self._tiles = source_delegate
        self._role = role
        self._colour = colour

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.text = ""    # no text; `DisplayRole` keeps the yes/no for the sort

    _LIST = amazetheme.drawn_list()    # the tick box sizes come from the L01 frame ▸r/list-from-frame
    SIDE = theme.ui_px(_LIST["tick_side"])    # the mark's own side; a tick column is this plus PAD each side
    PAD = theme.ui_px(_LIST["tick_pad"])

    def _box(self, rect):
        """The tick's square at the cell's left edge, where the other columns start."""
        side = max(min(rect.height() - theme.ui_px(6), self.SIDE), 1)
        return QtCore.QRect(rect.left() + self.PAD, rect.top(),
                            side, rect.height())

    def sizeHint(self, option, index):
        return QtCore.QSize(self.SIDE + 2 * self.PAD,           # as wide as the mark, not the word
                            super().sizeHint(option, index).height())

    def paint(self, painter, option, index):
        super().paint(painter, option, index)   # the cell first: band, alternate colour, hover
        if self._role is None:
            return
        if not index.siblingAtColumn(0).data(self._role):
            return
        self._tiles._paint_check_mark(
            painter, self._box(option.rect), self._colour)


class CategoryCellDelegate(GridCellDelegate):
    """The category column's text colour: SELECTED_TEXT if selected, else its own, made readable."""

    def __init__(self, tiles, parent=None):
        super().__init__(parent)
        self._tiles = tiles

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        if option.state & QtWidgets.QStyle.StateFlag.State_Selected:
            return      # a selected row has ONE text colour, already set by the base class
        raw = index.data(QtCore.Qt.ItemDataRole.ForegroundRole)
        if raw is None:
            return
        option.palette.setBrush(
            QtGui.QPalette.ColorRole.Text,
            QtGui.QBrush(self._tiles.readable_on(
                QtGui.QColor(raw), option.palette.base().color())))


class AssetItemDelegate(QtWidgets.QStyledItemDelegate):
    """Paints a tile as thumbnail, name and subtitle; a failure falls back to the default painting."""

    _TILE = amazetheme.drawn_tile()    # every spacing below is the T01 frame's ▸r/tile-from-frame
    PAD = theme.ui_px(_TILE["pad"])
    WIDTH_EXTRA = theme.ui_px(_TILE["width_extra"])    # cell width = size + this
    PLACES = {name: (edge_x, theme.ui_px(ix), edge_y, theme.ui_px(iy), theme.ui_px(side))
              for name, (edge_x, ix, edge_y, iy, side) in amazetheme.drawn_badges().items()}
    BADGE_CAP = max(place[4] for place in PLACES.values()
                    if "centre" not in (place[0], place[2]))    # the corner badges' drawn size
    DRAWN_THUMB = theme.ui_px(_TILE["thumb"])    # the thumbnail side the T frames draw
    TEXT_COLOR = QtGui.QColor(amazetheme.TILE_TEXT)
    THUMB_BG_COLOR = theme.color("surface_low")    # the dark card behind the thumbnail and text

    GRID_NAME_COLOR = theme.color("text")           # the grid tile's name, in the neutral grey
    GRID_SUBTITLE_COLOR = theme.color("text_dim")   # and the subtitle a dimmer grey, never the accent
    GRID_TEXT_INSET = theme.ui_px(_TILE["text_inset"])
    GRID_BOTTOM_PAD = theme.ui_px(_TILE["bottom_pad"])
    GRID_IMG_TEXT_GAP = theme.ui_px(_TILE["img_text_gap"])
    GRID_LINE_GAP = theme.ui_px(_TILE["line_gap"])    # between the name's line and the subtitle's
    RENDERER_ICONS = {    # art name -> (height, inset from the card's right edge, bottom under the subtitle's)
        name: tuple(theme.ui_px(drawn[key]) for key in ("height", "inset", "below"))
        for name, drawn in amazetheme.drawn_renderer_icons().items()}
    RENDERER_ICON_BLEED = theme.ui_px(amazetheme.RENDERER_ICON_BLEED)    # room around it for its shadow

    CATEGORY_COLOR = QtGui.QColor(amazetheme.LIST_TEXT_COLOR)    # the Category column for a category with no colour
    LIST_TEXT_COLOR = QtGui.QColor(amazetheme.LIST_TEXT_COLOR)    # list mode's text colour, all but Category
    SELECTED_TEXT = QtGui.QColor(amazetheme.LIST_SELECTED_TEXT)     # every column's text colour on a selected row

    _badge_cache = {}    # rendered badge per (art, size, dpr, opacity), app-wide
    _font_cache = {}     # (`QFont.key()`, selected) -> (name_font, rend_font, fm, fm)

    @classmethod
    def grid_cell_size(cls, ts, base_font):
        """The `gridSize` matching `_paint`'s layout: square image, gap, two text lines, bottom pad."""
        pad = cls.PAD
        width = ts + cls.WIDTH_EXTRA
        icon_side = max(width - 2 * pad, 1)
        _nf, _rf, fm_name, fm_rend = cls.fonts_for(base_font, False)
        block_h = fm_name.height() + cls.GRID_LINE_GAP + fm_rend.height()
        height = (
            pad
            + icon_side
            + cls.GRID_IMG_TEXT_GAP
            + block_h
            + cls.GRID_BOTTOM_PAD
        )
        return QtCore.QSize(width, height)

    CATEGORY_STRIP = theme.ui_px(amazetheme.drawn_category_strip())    # its height, off frame T20

    @staticmethod
    def _relative_luminance(color):
        """WCAG relative luminance of a QColor, sRGB-linearised."""
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
    def readable_on(cls, color, background, floor=4.5):
        """`color` lightened or darkened until it reaches `floor` contrast on `background`, hue kept."""
        if cls.contrast_ratio(color, background) >= floor:
            return color
        toward_light = cls._relative_luminance(background) < 0.5   # move away from the background's luminance
        best = color
        for _step in range(20):
            best = best.lighter(115) if toward_light else best.darker(115)
            if cls.contrast_ratio(best, background) >= floor:
                return best
        return cls.CATEGORY_COLOR    # a colour that never reaches `floor` falls back to CATEGORY_COLOR

    def _category_color(self, index):
        """The category colour for this row, or None for a tile that shows none."""
        return role_color(index, self._category_color_role)

    @classmethod
    def fonts_for(cls, option_font, selected):
        """Cached (name_font, subtitle_font, name_metrics, subtitle_metrics); never mutate them."""
        key = (option_font.key(), selected)    # `QFont.key()`: pixel-sized fonts too ▸r/font-sizing
        cached = cls._font_cache.get(key)
        if cached is None:
            name_font = QtGui.QFont(option_font)
            rend_font = QtGui.QFont(option_font)
            name_font.setBold(True)    # the name is bold, the subtitle regular
            points = theme.point_size(name_font)    # None for a pixel-sized font ▸r/font-sizing
            if points is not None:
                rend_font.setPointSizeF(points)    # the subtitle takes the name's size
            if selected:
                name_font.setBold(True)    # both lines are bold on a selected tile
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
        tag_role=None, licence_role=None,
        crop_role=None,
        category_color_role=None,
        active_version_role=None,
        date_role=None,
        id_role=None,
        tile_badges=(),
        tile_model=None,
        on_badge=None,
        renderer_role=None,
    ):
        """Every role is optional; None means the delegate does not paint that thing."""
        super().__init__(parent)
        self._renderer_role = renderer_role    # a material's renderer: its icon at the subtitle's right end
        self._active_version_role = active_version_role    # the active version's name, list mode
        self._crop_role = crop_role            # per row: truthy fills and crops the tile; None never crops
        self._subtitle_role = subtitle_role
        self._category_role = category_role    # list mode's Category column; None leaves it empty
        self._tag_role = tag_role              # list mode's tag and licence columns; None omits them
        self._licence_role = licence_role
        self._date_role = date_role            # list mode's date and id columns ▸p/d03-retired
        self._id_role = id_role
        self._category_color_role = category_color_role    # the strip's colour; None: no strip
        self._badge_clicks = {}       # badge name -> handler; registering one makes that badge a button
        self._button_hover = None     # (badge name, QPersistentModelIndex) while the cursor is on a button badge
        self._button_down = False     # and whether the left button is held on it
        self._tile = tuple(BADGE[name].name for name in tile_badges)    # the section's badge IDs
        for badge in BADGES:    # each role number from the model, None where this tile lacks the badge
            if badge.role_attr:
                setattr(self, badge.role_attr, getattr(tile_model, badge.role)
                        if badge.name in self._tile else None)
            if badge.name in self._tile and badge.handler and on_badge is not None:
                self.set_badge_click(badge.name, on_badge(badge.handler))

    @staticmethod
    def _to_pixmap(icon):
        """A thumbnail QImage, QPixmap or QIcon as a QPixmap, or None when there is nothing."""
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
        """`source` filling a `target` square, the overflow centre-cropped, cached under `key`."""
        scaled = source.scaled(
            target,
            target,
            QtCore.Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        x = max(0, (scaled.width() - target) // 2)     # centre-crop
        y = max(0, (scaled.height() - target) // 2)
        cropped = scaled.copy(x, y, target, target)
        cropped.setDevicePixelRatio(dpr)
        QtGui.QPixmapCache.insert(key, cropped)
        return cropped

    @staticmethod
    def _icon_pixmap(icon, side, dpr=1.0, cover=False):
        """A cached tile pixmap at device resolution, ratio set; place it by `_logical_size`."""
        target = max(1, round(side * dpr))
        if isinstance(icon, QtGui.QImage) and not icon.isNull():
            key = "amaze_%s_%s_%s_%s" % (      # a re-rendered thumbnail is a new key ▸r/tile-image-cache
                icon.cacheKey(), side, dpr, cover)
            cached = QtGui.QPixmapCache.find(key)
            if cached is not None and not cached.isNull():
                return cached
            return AssetItemDelegate._scale_and_cache(
                QtGui.QPixmap.fromImage(icon), key, target, dpr, cover)
        pixmap = AssetItemDelegate._to_pixmap(icon)
        if pixmap is None:
            return None
        key = "amaze_pm_%s_%s_%s_%s" % (     # cached too, or it rescales every repaint ▸r/tile-image-cache
            pixmap.cacheKey(), side, dpr, cover)
        cached = QtGui.QPixmapCache.find(key)
        if cached is not None and not cached.isNull():
            return cached
        return AssetItemDelegate._scale_and_cache(
            pixmap, key, target, dpr, cover)

    @staticmethod
    def _scale_and_cache(pixmap, key, target, dpr, cover):
        """Cover-crop or aspect-fit `pixmap` to `target`, pixel ratio set, cached under `key`."""
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
        """The logical (w, h) of a pixmap whose `devicePixelRatio` may be set."""
        r = pixmap.devicePixelRatio() or 1.0
        return round(pixmap.width() / r), round(pixmap.height() / r)

    @classmethod
    def _badge_pixmap(cls, name, side, dpr=1.0, opacity=None):
        """One tile badge at DEVICE resolution, as drawn or at a button opacity, cached per all four."""
        key = (name, side, round(dpr, 3), opacity)
        pixmap = cls._badge_cache.get(key)
        if pixmap is None:
            path = amaze.package_file("ui", name + ".svg")
            if os.path.exists(path):
                pixmap = ui_helpers.device_pixmap(path, side, dpr, opacity=opacity)
            else:
                pixmap = QtGui.QPixmap()    # null, so a missing badge paints nothing
            cls._badge_cache[key] = pixmap
        return pixmap

    @staticmethod
    def _button_opacity(hovered) -> float:
        """The rest or hover opacity shared by every button badge."""
        return amazetheme.BADGE_HOVER_OPACITY if hovered else amazetheme.BADGE_REST_OPACITY

    @classmethod
    def _badge_side(cls, icon_side, cap=None):
        """A badge grows with the tile up to its drawn size, never below 12px."""
        return max(theme.ui_px(12), min(icon_side // 4, cap or cls.BADGE_CAP))

    def _badge_at(self, name, area_x, area_y, icon_side, mark_w=None, mark_h=None):
        """(x, y, w, h) of a badge on a thumbnail, from its drawn edges and insets."""
        edge_x, inset_x, edge_y, inset_y, cap = self.PLACES[name]
        side = self._placed_side(name, icon_side)
        w = side if mark_w is None else mark_w
        h = side if mark_h is None else mark_h
        scale = icon_side / float(self.DRAWN_THUMB)
        return (int(self._along(area_x, icon_side, w, edge_x, inset_x, scale)),
                int(self._along(area_y, icon_side, h, edge_y, inset_y, scale)),
                int(w), int(h))

    def _placed_side(self, name, icon_side):
        """A corner badge's side follows `_badge_side`; a centred one scales with the tile."""
        edge_x, _ix, edge_y, _iy, cap = self.PLACES[name]
        if "centre" in (edge_x, edge_y):
            return max(theme.ui_px(12),
                       min(cap, int(round(cap * icon_side / float(self.DRAWN_THUMB)))))
        return self._badge_side(icon_side, cap)

    @staticmethod
    def _along(start, span, size, edge, inset, scale):
        if edge == "centre":
            return start + span / 2.0 + inset * scale - size / 2.0
        if edge == "end":
            return start + span - size - inset
        return start + inset

    FAV_MARK_COLOR = LIST_TEXT_COLOR      # the mark columns' colour: LIST_TEXT_COLOR, like every other list column
    OPEN_MARK_COLOR = LIST_TEXT_COLOR
    NOTE_MARK_COLOR = LIST_TEXT_COLOR

    @staticmethod
    def _paint_check_mark(painter, rect, color):
        """Draw a tick in `color` centred in `rect`, the badge art's own shape; nothing under 4px."""
        side = min(rect.width(), rect.height())
        if side < 4:
            return
        scale = side / 44.0    # the badge art's check in its 44-unit box
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

    def set_badge_click(self, name, callback) -> None:
        """Register `callback(index)` as the click handler of badge `name`, making it a button."""
        self._badge_clicks[name] = callback

    def set_button_hover(self, name, index, down=False) -> bool:
        """Remember the button badge under the cursor and whether it is held; True when either changed."""
        current = self._button_hover
        new = (name, QtCore.QPersistentModelIndex(index)) if (
            name and index is not None and index.isValid()) else None    # rows move under filters
        down = bool(down and new is not None)
        moved = (current is None) != (new is None) or (
            new is not None and current is not None
            and (current[0] != new[0]
                 or QtCore.QModelIndex(current[1]) != QtCore.QModelIndex(new[1])))
        if not moved and down == self._button_down:
            return False
        self._button_hover = new
        self._button_down = down
        return True

    def _is_button_hovered(self, name, index) -> bool:
        hover = self._button_hover
        return (hover is not None and hover[0] == name
                and hover[1].isValid()
                and QtCore.QModelIndex(hover[1]) == index)

    def _is_button_pressed(self, name, index) -> bool:
        return self._button_down and self._is_button_hovered(name, index)

    def button_badge_at(self, index, option_rect, point):
        """The wired BUTTON badge drawn under `point` on this tile, or None."""
        if not index.isValid():
            return None
        for badge in BADGES:
            if (badge.name in self._badge_clicks
                    and self._badge_state(badge, index)
                    and self._badge_rect(option_rect, badge.name).contains(point)):
                return badge
        return None

    def _badge_state(self, badge, index) -> str:
        """"on", "off" or "" (not drawn) for one badge on one tile, for paint, click and tooltip."""
        if badge.name not in self._tile:
            return ""
        value = index.data(getattr(self, badge.role_attr)) if badge.role else True
        if value:
            return "on" if badge.is_on(value) else ""
        return "off" if badge.off_svg and badge.name in self._badge_clicks else ""    # a button at rest

    def _badge_rect(self, option_rect, name):
        """Where the badge `name` is drawn, for hit-testing: the placement `_paint_badges` uses."""
        pad = self.PAD
        icon_side = option_rect.width() - 2 * pad
        return QtCore.QRect(*self._badge_at(
            name, option_rect.left() + pad, option_rect.top() + pad, icon_side))

    def _badge_tooltip(self, badge, index):
        """A button badge's tooltip: the action a click takes from its current state."""
        if badge.off_tip and self._badge_state(badge, index) == "off":
            return badge.off_tip
        return badge.tip

    def helpEvent(self, event, view, option, index):
        """Show a width-capped tooltip: a button badge's own, else the tile's."""
        if (event is not None
                and event.type() == QtCore.QEvent.Type.ToolTip):
            badge = self.button_badge_at(index, option.rect, event.pos())
            words = self._badge_tooltip(badge, index) if badge else ""
            words = words or str(index.data(QtCore.Qt.ItemDataRole.ToolTipRole) or "")
            if words:
                QtWidgets.QToolTip.showText(
                    event.globalPos(),
                    ui_helpers.tooltip_text(words),
                    view)
                return True
        QtWidgets.QToolTip.hideText()
        return super().helpEvent(event, view, option, index)

    def editorEvent(self, event, model, option, index):
        """A left click released on a button badge runs its handler and is consumed."""
        if (event.type() == QtCore.QEvent.Type.MouseButtonRelease
                and event.button() == QtCore.Qt.MouseButton.LeftButton):
            badge = self.button_badge_at(
                index, option.rect, event.position().toPoint())
            if badge is not None:
                try:
                    self._badge_clicks[badge.name](index)
                except Exception as exc:                  # noqa: BLE001
                    debug.event("badges", "%s badge click handler "
                                "failed" % badge.name, error=str(exc))
                return True
        return super().editorEvent(event, model, option, index)

    def badges(self) -> tuple:
        """The badge IDs this tile shows, in paint order."""
        return tuple(badge.name for badge in BADGES if badge.name in self._tile)

    def _paint_badges(self, painter, index, area_x, area_y,
                      icon_side, dpr=1.0):
        """Every badge this tile carries, in one pass, each where the T frames draw it."""
        for badge in BADGES:
            state = self._badge_state(badge, index)
            if not state:
                continue
            hovered = self._is_button_hovered(badge.name, index)
            opacity = self._button_opacity(hovered)
            if state == "off" and hovered and badge.off_hover_svg:
                svg, opacity = badge.off_hover_svg, None
            elif state == "off":
                svg = badge.off_svg
            elif badge.press_svg and self._is_button_pressed(badge.name, index):
                svg, opacity = badge.press_svg, None
            elif badge.hover_svg and hovered:
                svg, opacity = badge.hover_svg, None
            else:
                svg = badge.svg
                opacity = opacity if badge.dims else None    # full opacity, so the on heart keeps its colour
            side = self._placed_side(badge.name, icon_side)
            mark = self._badge_pixmap(svg, side, dpr, opacity)
            if mark.isNull():
                continue
            mark_w, mark_h = self._logical_size(mark)    # logical, not physical, pixels
            x, y, _w, _h = self._badge_at(badge.name, area_x, area_y, icon_side,
                                          mark_w, mark_h)
            painter.drawPixmap(x, y, mark)

    def _renderer_icon(self, index, dpr):
        """The row's renderer icon, or None: no role, no renderer, or one Amaze does not offer."""
        if self._renderer_role is None:
            return None
        renderer = renderers.get(index.data(self._renderer_role))
        if renderer is None or renderer.tile_icon not in self.RENDERER_ICONS:
            return None
        mark = self._renderer_pixmap(renderer.tile_icon, dpr)
        return None if mark.isNull() else (mark,) + self.RENDERER_ICONS[renderer.tile_icon][1:]

    @classmethod
    def _renderer_pixmap(cls, name, dpr=1.0):
        """A renderer's icon at DEVICE resolution: its own shape plus the bleed around it; cached."""
        height = cls.RENDERER_ICONS[name][0]
        key = ("renderer", name, height, round(dpr, 3))
        pixmap = cls._badge_cache.get(key)
        if pixmap is None:
            pixmap = ui_helpers.bled_pixmap(amaze.package_file("ui", name + ".svg"),
                                            height, dpr, cls.RENDERER_ICON_BLEED)
            cls._badge_cache[key] = pixmap
        return pixmap

    def sizeHint(self, option, index):
        """The view's own `gridSize`, exactly, when it has one; else the base hint."""
        try:
            grid = option.widget.gridSize()
            if grid.isValid() and grid.height() > 0 and grid.width() > 0:
                return grid
        except Exception:
            pass
        return super().sizeHint(option, index)

    def paint(self, painter, option, index):
        """`_paint` inside a balanced save/restore; a failure falls back to the default painting."""
        try:
            painter.save()
            try:
                self._paint(painter, option, index)
            finally:
                painter.restore()
        except Exception:
            super().paint(painter, option, index)    # balanced again by the `finally` above, so the fallback paints on a clean painter

    def _paint(self, painter, option, index):
        """The tile itself: card, optional category strip, thumbnail, badges, then the two text lines."""
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
            dpr = option.widget.devicePixelRatioF()    # tile images render at device resolution
        except Exception:
            dpr = 1.0

        name_font, rend_font, fm_name, fm_rend = self.fonts_for(
            option.font, selected
        )
        h_name = fm_name.height()
        h_rend = fm_rend.height()

        raw_category = self._category_color(index)    # read once per tile

        pad = self.PAD
        text_x = rect.left() + pad + self.GRID_TEXT_INSET
        text_w = max(rect.width() - 2 * pad - self.GRID_TEXT_INSET, 1)
        line_gap = self.GRID_LINE_GAP
        block_h = h_name + line_gap + h_rend    # both lines, subtitle or not, as `grid_cell_size` reserves
        name_dy = 0 if renderer else (line_gap + h_rend) // 2    # a lone name is centred in the block
        icon_side = max(rect.width() - 2 * pad, 1)
        icon_x = rect.left() + pad
        icon_y = rect.top() + pad
        text_top = icon_y + icon_side + self.GRID_IMG_TEXT_GAP
        card_bottom = text_top + block_h + self.GRID_BOTTOM_PAD    # one card under image and text
        painter.fillRect(
            QtCore.QRect(
                icon_x, icon_y, icon_side, card_bottom - icon_y
            ),
            self.THUMB_BG_COLOR,
        )
        if raw_category is not None and not selected:    # the category colour, a strip under the image
            painter.fillRect(
                QtCore.QRect(icon_x, icon_y + icon_side, icon_side, self.CATEGORY_STRIP), raw_category)
        if selected:
            zone_top = icon_y + icon_side    # repaint the highlight on the text area only
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
        subtitle_top = text_top + h_name + line_gap
        subtitle_w = text_w
        placed = self._renderer_icon(index, dpr)
        if placed is not None:    # at the subtitle's right end; the subtitle ends a text inset before it
            mark, inset, below = placed
            bleed = self.RENDERER_ICON_BLEED
            full_w, full_h = self._logical_size(mark)
            mark_w, mark_h = full_w - 2 * bleed, full_h - 2 * bleed    # the icon's own box
            mark_x = icon_x + icon_side - inset - mark_w
            mark_y = subtitle_top + h_rend + below - mark_h
            painter.drawPixmap(mark_x - bleed, mark_y - bleed, mark)
            subtitle_w = max(mark_x - self.GRID_TEXT_INSET - text_x, 1)
        painter.setFont(name_font)
        painter.setPen(self.SELECTED_TEXT if selected else self.GRID_NAME_COLOR)
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
            painter.setPen(self.SELECTED_TEXT if selected else self.GRID_SUBTITLE_COLOR)
            painter.drawText(
                QtCore.QRect(text_x, subtitle_top, subtitle_w, h_rend),
                QtCore.Qt.AlignmentFlag.AlignLeft
                | QtCore.Qt.AlignmentFlag.AlignVCenter,
                fm_rend.elidedText(
                    renderer, QtCore.Qt.TextElideMode.ElideRight, subtitle_w
                ),
            )


class SidebarItemDelegate(QtWidgets.QStyledItemDelegate):
    """Paints sidebar rows (name, count, colour bar) through `initStyleOption` and the host style."""

    PAD = theme.ui_px(6)
    _swatch_cache = {}   # decoration QIcon per (side, rgba or None, arrow, ratio)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.show_counts = True    # False hides each category's count; All always shows its total
        self.drag_index = QtCore.QPersistentModelIndex()    # the row a drop would go to; no row when invalid
        self._drag_color = QtGui.QColor(amazetheme.TILE_SUBTITLE)    # until the panel sets the accent
        self.color_role = None     # the role carrying a category's colour, or None for none

    def set_drag_color(self, color: QtGui.QColor) -> None:
        self._drag_color = QtGui.QColor(color)

    def drop_target(self, index) -> bool:
        """Whether `index` is the drop target, by index not row: a tree numbers rows per parent."""
        return (self.drag_index.isValid()
                and QtCore.QPersistentModelIndex(index) == self.drag_index)

    def helpEvent(self, event, view, option, index):
        """A row's tooltip, such as a folder's path, width-capped by `show_capped_tooltip`."""
        return (show_capped_tooltip(event, view, index)
                or super().helpEvent(event, view, option, index))

    def _swatch_color(self, index):
        """This row's category colour, or None; invalid values are ignored rather than painted."""
        return role_color(index, self.color_role)

    BAR = theme.ui_px(amazetheme.drawn_sidebar()["bar"])    # from G01; EVERY row reserves it, so all labels align
    ARROW_GAP = theme.ui_px(amazetheme.SIDEBAR_ARROW_GAP)    # in a folder tree: bar, gap, arrow
    ARROW_BOX = theme.ui_px(amazetheme.SIDEBAR_ARROW_BOX)

    def _arrow(self, index):
        """None in a flat sidebar; in a folder tree "open", "closed", or "" with no subfolders."""
        view = self.parent()
        model = index.model()
        if not isinstance(view, QtWidgets.QTreeView) or not getattr(model, "unfolds", False):
            return None
        if not model.hasChildren(index):
            return ""
        return "open" if view.isExpanded(index) else "closed"

    def _ratio(self) -> float:
        view = self.parent()
        return view.devicePixelRatioF() if isinstance(view, QtWidgets.QWidget) else 1.0

    def _decoration(self, side: int, swatch, arrow):
        """The row's decoration: the colour bar, then, in a folder tree, the arrow's box."""
        if arrow is None:    # a flat sidebar: the bar alone, as G01 draws it
            pixmap = QtGui.QPixmap(self.BAR, side)
            pixmap.fill(swatch if swatch is not None else QtGui.QColor(0, 0, 0, 0))
            return QtGui.QIcon(pixmap)
        ratio = self._ratio()
        width = self.BAR + self.ARROW_GAP + self.ARROW_BOX
        pixmap = QtGui.QPixmap(round(width * ratio), round(side * ratio))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(QtGui.QColor(0, 0, 0, 0))
        painter = QtGui.QPainter(pixmap)
        if swatch is not None:
            painter.fillRect(QtCore.QRectF(0, 0, self.BAR, side), swatch)
        if arrow:
            view = self.parent()
            flag = QtWidgets.QStyle.StateFlag
            option = QtWidgets.QStyleOptionViewItem()    # as QTreeView asks; the base class ends Houdini on Windows
            view.initViewItemOption(option)
            option.rect = QtCore.QRect(self.BAR + self.ARROW_GAP, 0, self.ARROW_BOX, side)
            option.state = flag.State_Enabled | flag.State_Item | flag.State_Children
            if arrow == "open":
                option.state |= flag.State_Open
            view.style().drawPrimitive(QtWidgets.QStyle.PrimitiveElement.PE_IndicatorBranch,
                                       option, painter, view)    # Houdini's own chevron ▸r/tree-views
        painter.end()
        return QtGui.QIcon(pixmap)

    def arrow_box(self, decoration: QtCore.QRect) -> QtCore.QRect:
        """The part of a folder row's decoration its arrow is drawn in."""
        return QtCore.QRect(decoration.x() + self.BAR + self.ARROW_GAP, decoration.y(),
                            self.ARROW_BOX, decoration.height())

    def initStyleOption(self, option, index):
        """The row as view-item fields for the style; `option.text` does not change DisplayRole."""
        super().initStyleOption(option, index)
        name = option.text    # the row's DisplayRole, which the base class has just read
        count = index.data(category.SIDEBAR_COUNT_ROLE)    # read even when hidden; each All row computes its own count
        if not self.show_counts and name != "All":
            count = None
        if count is not None:
            option.text = "%s (%s)" % (name, count)
        if option.state & QtWidgets.QStyle.StateFlag.State_Selected:
            font = QtGui.QFont(option.font)
            font.setBold(True)
            option.font = font
        side = max(QtGui.QFontMetrics(option.font).height(), 1)    # from the font, never `option.rect`
        swatch = self._swatch_color(index)
        arrow = self._arrow(index)
        key = (side, swatch.rgba() if swatch is not None else None, arrow,
               self._ratio() if arrow is not None else 1.0)
        icon = self._swatch_cache.get(key)
        if icon is None:
            icon = self._swatch_cache[key] = self._decoration(side, swatch, arrow)
        option.icon = icon    # a DECORATION, so the style lays the name out after it
        width = self.BAR if arrow is None else self.BAR + self.ARROW_GAP + self.ARROW_BOX
        option.decorationSize = QtCore.QSize(width, side)
        option.features |= (
            QtWidgets.QStyleOptionViewItem.ViewItemFeature.HasDecoration)
        if self.drop_target(index):
            option.backgroundBrush = QtGui.QBrush(self._drag_color)    # drop-target feedback
