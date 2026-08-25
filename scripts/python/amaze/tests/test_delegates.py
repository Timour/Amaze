"""Painting contracts for the tile/row delegates: Qt drives every visible item with ONE painter, so a delegate that mishandles it corrupts every tile painted after it in the same pass, and these pin the invariants that keep a delegate a good citizen of a shared painter."""

import os
import sys
import unittest

sys.path.insert(   # THREE dirnames up = scripts/python, holding the `amaze` package - the DEV tree, not the install on Houdini's path
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # BEFORE the app exists ▸p/first-app-picks-the-platform
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401
from amaze.panel import delegates  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401 - redirects the debug log


class _ExplodingModel(QtCore.QAbstractListModel):
    """A model whose row 1 raises, the way a real row does when it vanishes between layout and paint: library.py indexes `_assets` with the view's row and has no bounds check, so a reload or a switch under a scrolled grid raises IndexError straight out of data()."""

    def __init__(self, only_role=None):
        super().__init__()
        self._only_role = only_role  # raise only for this role, to fail LATE in _paint (after pens and fonts are set) rather than on the first read

    def rowCount(self, parent=None):
        return 3

    def data(self, index, role=0):
        if index.row() == 1 and (
                self._only_role is None or role == self._only_role):
            raise IndexError("list index out of range")
        return "row %d" % index.row()


class TheSvgCacheTest(unittest.TestCase):
    """Every icon used to be a fresh file read, XML parse and raster - 30-35 at construction alone, duplicates and hidden chrome included; here because a QPixmap needs a QApplication, which this module has and the database tests do not."""

    def setUp(self):
        from amaze.helpers import ui_helpers
        self.ui_helpers = ui_helpers
        self.icon = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "ui", "icon_view.svg")
        if not os.path.isfile(self.icon):
            self.skipTest("no shipped icon to render")
        ui_helpers._SVG_CACHE.clear()
        self.addCleanup(ui_helpers._SVG_CACHE.clear)

    def test_the_second_ask_does_not_render_again(self):
        self.ui_helpers.render_svg_pixmap(self.icon, 32)
        self.assertEqual(1, len(self.ui_helpers._SVG_CACHE))
        self.ui_helpers.render_svg_pixmap(self.icon, 32)
        self.assertEqual(1, len(self.ui_helpers._SVG_CACHE),
                         "the second ask rendered the file again")

    def test_a_different_tint_is_a_different_picture(self):
        self.ui_helpers.render_svg_pixmap(self.icon, 32)
        self.ui_helpers.render_svg_pixmap(
            self.icon, 32, {"#5d7abd": "#ff0000"})
        self.assertEqual(
            2, len(self.ui_helpers._SVG_CACHE),
            "a tinted render reused the untinted picture")

    def test_a_size_is_part_of_the_key(self):
        self.ui_helpers.render_svg_pixmap(self.icon, 32)
        self.ui_helpers.render_svg_pixmap(self.icon, 64)
        self.assertEqual(2, len(self.ui_helpers._SVG_CACHE))

    def test_the_caller_never_receives_the_cached_pixmap_itself(self):
        """QPixmap is mutable: hand out the cached object and a caller that paints into it poisons every later ask for that icon."""
        first = self.ui_helpers.render_svg_pixmap(self.icon, 32)
        second = self.ui_helpers.render_svg_pixmap(self.icon, 32)
        self.assertIsNot(first, second)
        cached = self.ui_helpers._SVG_CACHE[(self.icon, 32, ())]
        self.assertIsNot(first, cached)


class PainterBalanceTest(unittest.TestCase):
    """A delegate must hand the painter back exactly as it got it: with save() at the top of _paint and restore() at the bottom, a row raising in between skipped the restore, so the fallback row and every row after it in that pass inherited the leaked pen, font and clip while the save stack grew by one per failing tile - measured before the fix as Qt's own `QPainter::end: Painter ended with 1 saved states`."""

    def setUp(self):
        self.messages = []
        QtCore.qInstallMessageHandler(
            lambda mode, ctx, message: self.messages.append(message))
        self.addCleanup(QtCore.qInstallMessageHandler, None)

        self.view = QtWidgets.QListView()
        self.addCleanup(self.view.deleteLater)
        self.delegate = delegates.AssetItemDelegate(
            QtCore.Qt.ItemDataRole.UserRole + 3, parent=self.view)

    def _paint_row(self, model, row):
        """Paint one row and end the painter, returning the painter's (pen colour, font size) before and after."""
        self.view.setModel(model)
        image = QtGui.QImage(400, 300, QtGui.QImage.Format.Format_ARGB32)
        painter = QtGui.QPainter(image)

        painter.setPen(QtGui.QColor("#ff0000"))
        painter.setFont(QtGui.QFont("Courier", 31))
        before = (painter.pen().color().name(), painter.font().pointSize())

        option = QtWidgets.QStyleOptionViewItem()
        option.rect = QtCore.QRect(0, 0, 120, 90)
        option.widget = self.view
        option.font = self.view.font()
        option.palette = self.view.palette()
        try:
            self.delegate.paint(painter, option, model.index(row, 0))
        except Exception:
            pass  # the fallback super().paint() re-reads the same bad row and raises too; what matters here is the state the painter is left in

        after = (painter.pen().color().name(), painter.font().pointSize())
        painter.end()
        return before, after

    def test_a_failing_tile_leaves_the_save_stack_balanced(self):
        self._paint_row(_ExplodingModel(), 1)
        unbalanced = [m for m in self.messages if "saved states" in m]
        self.assertEqual(
            [], unbalanced,
            "the delegate left the shared painter with an unbalanced save "
            "stack; every row painted after it inherits the leaked state")

    def test_no_pen_or_font_leaks_however_late_the_failure(self):
        """Raising on the LAST role _paint reads: measured, it reads exactly three - Decoration(1), Display(0), subtitle(259) - all BEFORE touching the painter, so a raising model cannot leave a pen or font behind however late it fails, and this pins that ordering, going red if an edit moves a model read after the first setPen."""
        model = _ExplodingModel(
            only_role=QtCore.Qt.ItemDataRole.UserRole + 3)
        before, after = self._paint_row(model, 1)
        self.assertEqual(
            before, after,
            "a failing tile left its pen/font on the shared painter")

    def test_a_healthy_tile_still_paints_and_stays_balanced(self):
        """The guard must not break the normal path."""
        before, after = self._paint_row(_ExplodingModel(), 0)
        self.assertEqual(before, after)
        self.assertEqual(
            [], [m for m in self.messages if "saved states" in m])


class _RectSpy(QtGui.QPainter):
    """Records every fillRect, so the card's real extent is measured rather than inferred from pixels."""

    def __init__(self, device):
        super().__init__(device)
        self.rects = []

    def fillRect(self, *args):
        if args and isinstance(args[0], QtCore.QRect):
            self.rects.append(QtCore.QRect(args[0]))
        return super().fillRect(*args)


class CardFillsItsCellTest(unittest.TestCase):
    """A tile with no subtitle must not have a shorter card: grid_cell_size always reserves both text heights while _paint sized the card from the text it was about to DRAW, so a material with an empty renderer label got a card - and a category colour band - 18px shorter than its own cell, bare grid background underneath, beside normal tiles at every slider size (measured at ts=128, cell height 180: card bottom 179 with a subtitle, 161 without). `grid_cell_size` reserves `fm_name.height() + fm_rend.height()` while `_paint` sized from `h_name + (h_rend if renderer else 0)`, and `library.renderer_label` answers "" for a renderer it does not know - which is how a real row reaches the short branch."""

    SUBTITLE = QtCore.Qt.ItemDataRole.UserRole + 3

    class _Model(QtCore.QAbstractListModel):
        def __init__(self, subtitle):
            super().__init__()
            self._subtitle = subtitle

        def rowCount(self, parent=None):
            return 1

        def data(self, index, role=0):
            if role == CardFillsItsCellTest.SUBTITLE:
                return self._subtitle
            if role == QtCore.Qt.ItemDataRole.DisplayRole:
                return "material_name"
            return None

    def _card_bottom(self, subtitle, thumbsize=128):
        view = QtWidgets.QListView()
        self.addCleanup(view.deleteLater)
        view.setViewMode(QtWidgets.QListView.ViewMode.IconMode)  # IconMode is the GRID: a default QListView is in ListMode, and forgetting this measures the wrong branch entirely
        model = self._Model(subtitle)
        view.setModel(model)
        delegate = delegates.AssetItemDelegate(self.SUBTITLE, parent=view)

        cell = delegate.grid_cell_size(thumbsize, view.font())
        image = QtGui.QImage(cell.width(), cell.height(),
                             QtGui.QImage.Format.Format_ARGB32)
        painter = _RectSpy(image)
        option = QtWidgets.QStyleOptionViewItem()
        option.rect = QtCore.QRect(0, 0, cell.width(), cell.height())
        option.widget = view
        option.font = view.font()
        option.palette = view.palette()
        delegate.paint(painter, option, model.index(0, 0))
        rects = list(painter.rects)
        painter.end()
        self.assertTrue(rects, "the delegate filled nothing at all")
        return cell.height(), max(r.bottom() for r in rects)

    def test_a_tile_without_a_subtitle_has_a_full_height_card(self):
        with_sub_h, with_sub = self._card_bottom("Karma")
        without_h, without = self._card_bottom("")
        self.assertEqual(with_sub_h, without_h, "the CELL size changed too")
        self.assertEqual(
            with_sub, without,
            "a tile with no subtitle has a card %dpx shorter than one "
            "with a subtitle - bare grid background shows under it"
            % (with_sub - without))

    def test_the_card_reaches_the_bottom_of_its_cell(self):
        height, bottom = self._card_bottom("")
        self.assertGreaterEqual(
            bottom, height - 1,
            "the card stops %dpx short of its own cell" % (height - 1 - bottom))


class BandContrastTest(unittest.TestCase):
    """A category colour must never make its own label unreadable: `text_on` picked its ink from a Rec. 601 luminance threshold at 140, putting the cut just inside the green ramp - #00ee00 measures 139.7 and took the LIGHT ink, near-white on bright green at 1.37:1, with 8.7%% of the RGB cube below 3:1."""

    DELEGATE = delegates.AssetItemDelegate

    def _sweep(self, step=15):
        for red in range(0, 256, step):
            for green in range(0, 256, step):
                for blue in range(0, 256, step):
                    yield QtGui.QColor(red, green, blue)

    def test_no_colour_makes_its_label_unreadable(self):
        worst, worst_color = 21.0, None
        for color in self._sweep():
            ratio = self.DELEGATE.contrast_ratio(
                color, self.DELEGATE.text_on(color))
            if ratio < worst:
                worst, worst_color = ratio, color
        self.assertGreaterEqual(
            worst, 3.0,
            "a category colour drops its label below 3:1 (%s at %.2f:1)"
            % (worst_color.name() if worst_color else "?", worst))

    def test_the_green_ramp_case_specifically(self):
        """The colour that exposed the threshold."""
        green = QtGui.QColor("#00ee00")
        self.assertGreater(
            self.DELEGATE.contrast_ratio(
                green, self.DELEGATE.text_on(green)),
            4.5, "near-white ink is back on bright green")

    def test_the_shipped_presets_are_unchanged(self):
        """The rule change must not restyle what is already saved: all four presets measured identically under both rules."""
        from amaze.core import tile_icons

        for _name, value in tile_icons.PRESETS:
            color = QtGui.QColor(value)
            self.assertGreater(
                self.DELEGATE.contrast_ratio(
                    color, self.DELEGATE.text_on(color)),
                4.5, "preset %s lost contrast" % value)

    def test_a_dark_category_is_legible_in_list_mode(self):
        """List mode paints the colour as the PEN on the row instead of filling a band and had no contrast rule at all - #333333 measured 1.03:1 against the row."""
        row = QtGui.QColor("#313131")
        for value in ("#333333", "#262626", "#1a1a1a", "#000000"):
            adjusted = self.DELEGATE.readable_on(QtGui.QColor(value), row)
            self.assertGreaterEqual(
                self.DELEGATE.contrast_ratio(adjusted, row), 4.0,
                "%s stays invisible in list mode" % value)

    def test_the_CATEGORY_CELL_actually_applies_the_legibility_pass(self):
        """The test above proves `readable_on` is correct; this proves something CALLS it, because otherwise deleting the call site changes nothing a unit test can see - the site is `CategoryCellDelegate.initStyleOption`, the only place that knows both the colour and what it is drawn on."""
        view = QtWidgets.QTableView()
        self.addCleanup(view.deleteLater)
        palette = view.palette()
        palette.setColor(QtGui.QPalette.ColorRole.Base,
                         QtGui.QColor("#313131"))
        view.setPalette(palette)
        model = QtGui.QStandardItemModel()
        item = QtGui.QStandardItem("Metal")
        item.setData(QtGui.QColor("#333333"),
                     QtCore.Qt.ItemDataRole.ForegroundRole)
        model.appendRow(item)
        view.setModel(model)

        tiles = delegates.AssetItemDelegate(
            QtCore.Qt.ItemDataRole.UserRole + 3, parent=view)
        delegate = delegates.CategoryCellDelegate(tiles, view)

        seen = []
        real = delegates.AssetItemDelegate.__dict__["readable_on"]
        unwrapped = real.__func__

        def record(cls, color, background, floor=4.5):
            seen.append(QtGui.QColor(color).name())
            return unwrapped(cls, color, background, floor)

        delegates.AssetItemDelegate.readable_on = classmethod(record)
        self.addCleanup(
            setattr, delegates.AssetItemDelegate, "readable_on", real)

        option = QtWidgets.QStyleOptionViewItem()
        option.rect = QtCore.QRect(0, 0, 120, 20)
        option.widget = view
        option.font = view.font()
        option.palette = view.palette()
        option.state = QtWidgets.QStyle.StateFlag.State_Enabled
        delegate.initStyleOption(option, model.index(0, 0))

        self.assertIn(
            "#333333", seen,
            "the Category cell used the raw colour - a dark one is "
            "invisible against the row")
        self.assertNotEqual(
            "#333333",
            option.palette.color(QtGui.QPalette.ColorRole.Text).name(),
            "the pass ran and its answer was thrown away")

    def test_a_colour_that_already_reads_is_left_alone(self):
        """The adjustment must not restyle colours that were fine - the colour identifies the category, so the hue has to survive."""
        row = QtGui.QColor("#313131")
        for _name, value in __import__(
                "amaze.core.tile_icons", fromlist=["x"]).PRESETS:
            color = QtGui.QColor(value)
            self.assertEqual(
                color.name(),
                self.DELEGATE.readable_on(color, row).name(),
                "preset %s was altered although it already reads" % value)


class PaintCostTest(unittest.TestCase):
    """Two things the grid was paying for and not using."""

    COLOR_ROLE = QtCore.Qt.ItemDataRole.UserRole + 8
    SUBTITLE = QtCore.Qt.ItemDataRole.UserRole + 3

    def _counting_model(self, reads):
        role, subtitle = self.COLOR_ROLE, self.SUBTITLE

        class _Counting(QtCore.QAbstractListModel):
            def rowCount(self, parent=None):
                return 60

            def data(self, index, data_role=0):
                if data_role == role:
                    reads.append(1)
                    return "#4af2a1"
                if data_role == subtitle:
                    return "Karma"
                if data_role == QtCore.Qt.ItemDataRole.DisplayRole:
                    return "mat"
                return None

        return _Counting()

    def test_the_category_colour_is_read_once_per_tile(self):
        """The grid resolved it and then asked again for its band - 120 reads for 60 tiles against list mode's 60, each a full proxy-to-source round trip plus a QColor parse, costing 0.31ms of every 8.57ms repaint."""
        reads = []
        model = self._counting_model(reads)
        view = QtWidgets.QListView()
        self.addCleanup(view.deleteLater)
        view.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
        view.setModel(model)
        delegate = delegates.AssetItemDelegate(
            self.SUBTITLE, parent=view,
            category_role=QtCore.Qt.ItemDataRole.UserRole + 1,
            category_color_role=self.COLOR_ROLE)

        image = QtGui.QImage(200, 200, QtGui.QImage.Format.Format_ARGB32)
        painter = QtGui.QPainter(image)
        option = QtWidgets.QStyleOptionViewItem()
        option.rect = QtCore.QRect(0, 0, 180, 180)
        option.widget = view
        option.font = view.font()
        option.palette = view.palette()
        reads.clear()
        for row in range(60):
            delegate.paint(painter, option, model.index(row, 0))
        painter.end()

        self.assertEqual(
            60, len(reads),
            "the grid read the category colour %d times for 60 tiles"
            % len(reads))

    def test_a_badge_is_rendered_at_device_resolution(self):
        """It rasterised at the logical size and drew 1:1, so on Retina a 22x22 badge was upscaled onto a 44x44 area - soft on top of thumbnails `_icon_pixmap` renders at side*dpr."""
        normal = delegates.AssetItemDelegate._badge_pixmap(
            "badge_star", 22, 1.0)
        retina = delegates.AssetItemDelegate._badge_pixmap(
            "badge_star", 22, 2.0)
        if normal.isNull() or retina.isNull():
            self.skipTest("badge_star.svg not resolvable outside an install")
        self.assertEqual(
            44, retina.width(),
            "the Retina badge is still rasterised at logical size")
        self.assertAlmostEqual(2.0, retina.devicePixelRatio(), places=3)
        self.assertNotEqual(normal.cacheKey(), retina.cacheKey())  # and the two must not share a cache entry

    def test_badge_placement_uses_logical_size(self):
        """width() is PHYSICAL pixels once devicePixelRatio is set, so placing by it pushes the badge off the tile on Retina."""
        retina = delegates.AssetItemDelegate._badge_pixmap(
            "badge_star", 22, 2.0)
        if retina.isNull():
            self.skipTest("badge_star.svg not resolvable outside an install")
        logical_w, _h = delegates.AssetItemDelegate._logical_size(retina)
        self.assertEqual(
            22, logical_w,
            "the logical size helper disagrees with the rendered badge")
        self.assertNotEqual(
            logical_w, retina.width(),
            "this test proves nothing unless the two differ")


class BadgeFamilyTest(unittest.TestCase):
    """The four tile badges are ONE drawn family: one art set (each glyph on its own dark disc), one rasteriser (`_badge_pixmap`), one size rule (`_badge_side`) and rendered AS DRAWN with no re-tinting - four accreted looks with three size formulas made the corners hard to read on busy thumbnails."""

    NAMES = ("badge_open", "badge_star", "badge_versions",
             "badge_comment", "badge_comment_75")

    def test_all_four_arts_exist_and_render(self):
        for name in self.NAMES:
            mark = delegates.AssetItemDelegate._badge_pixmap(name, 22, 2.0)
            self.assertFalse(
                mark.isNull(),
                "%s.svg is missing or does not render" % name)

    def test_one_size_rule_grows_to_a_cap_with_a_list_floor(self):
        side = delegates.AssetItemDelegate._badge_side
        from amaze.helpers import theme
        self.assertEqual(
            theme.ui_px(22), side(1024),
            "a big grid tile's badge is not at the cap")
        self.assertEqual(
            theme.ui_px(12), side(16),
            "the LIST-mode floor is gone - a 16-point icon's badge "
            "shrinks past legibility")

    def _asked_for(self, role_kw, value, icon_side):
        """Wire ONE badge role, run the paint pass, record what it asks the rasteriser for - driving `_paint_badges` rather than a per-badge painter, so the loop is asserted to ask for the wired badge and NOTHING ELSE and a row reading the wrong role shows up as an extra request; behavioural rather than source-derived, and the dpr is recorded too, because recording only the side let a hardcoded 1.0 through and that rasterises at half size on a 2x display while every case stays green."""
        asked = []

        def spy(name, side, dpr=1.0):
            asked.append((name, side, dpr))
            return QtGui.QPixmap()          # null - nothing is drawn

        role = QtCore.Qt.ItemDataRole.UserRole + 77

        class _RoleModel(QtCore.QAbstractListModel):
            def rowCount(self, parent=QtCore.QModelIndex()):
                return 1

            def data(self, index, r=QtCore.Qt.ItemDataRole.DisplayRole):
                return value if r == role else None

        delegate = delegates.AssetItemDelegate(None, **{role_kw: role})
        model = _RoleModel()
        cls = delegates.AssetItemDelegate
        original = cls.__dict__["_badge_pixmap"]
        cls._badge_pixmap = staticmethod(spy)
        self.addCleanup(setattr, cls, "_badge_pixmap", original)

        surface = QtGui.QPixmap(64, 64)
        painter = QtGui.QPainter(surface)
        try:
            delegate._paint_badges(
                painter, model.index(0, 0), 0, 0, icon_side, 2.0)
        finally:
            painter.end()
        return asked

    def test_every_corner_asks_for_its_own_art_at_the_family_size(self):
        """All four painters, one engine: each corner requests ITS art by name, at `_badge_side`'s size, at the real dpr - a painter hand-rolling its own size or art goes red here."""
        cases = (
            ("open_role", True, "badge_open"),
            ("favorite_role", True, "badge_star"),
            ("versions_role", 3, "badge_versions"),
            ("notes_role", True, "badge_comment_75"),
        )
        expected = delegates.AssetItemDelegate._badge_side(128)
        self.assertEqual(
            len(cases), len(delegates.BADGES),
            "the badge table and this test disagree about how many "
            "badges there are - a new row must be driven here too")
        for role_kw, value, art in cases:
            asked = self._asked_for(role_kw, value, 128)
            self.assertEqual(
                [(art, expected, 2.0)], asked,
                "%s does not go through the family engine, or the pass "
                "asked for a badge nothing wired" % role_kw)

    def test_each_badge_lands_in_its_own_corner(self):
        """Four marks, four corners, none on top of another - found by a GREEN sabotage, since collapsing the corner arithmetic so every badge drew top-left failed nothing, and the failure it allows is silent because a stack of badges in one corner still paints a badge; each badge is rasterised as its own flat colour, so one pixel per corner says WHICH mark landed there."""
        colors = {
            "badge_open": QtGui.QColor(255, 0, 0),
            "badge_star": QtGui.QColor(0, 255, 0),
            "badge_versions": QtGui.QColor(0, 0, 255),
            "badge_comment_75": QtGui.QColor(255, 255, 0),
        }

        def flat(name, side, dpr=1.0):
            pixmap = QtGui.QPixmap(side, side)
            pixmap.fill(colors[name])
            return pixmap

        role = QtCore.Qt.ItemDataRole.UserRole + 88

        class _AllOn(QtCore.QAbstractListModel):
            def rowCount(self, parent=QtCore.QModelIndex()):
                return 1

            def data(self, index, r=QtCore.Qt.ItemDataRole.DisplayRole):
                return 3 if r == role else None  # 3 satisfies the versions badge's minimum of 2 and is truthy for the other three

        delegate = delegates.AssetItemDelegate(
            None, open_role=role, favorite_role=role, versions_role=role,
            notes_role=role)
        cls = delegates.AssetItemDelegate
        original = cls.__dict__["_badge_pixmap"]
        cls._badge_pixmap = staticmethod(flat)
        self.addCleanup(setattr, cls, "_badge_pixmap", original)

        side = 128
        model = _AllOn()   # HELD IN A LOCAL: `_AllOn().index(0, 0)` frees the model the moment the index exists, and reading data() off an index whose model is gone segfaults rather than raising
        index = model.index(0, 0)
        canvas = QtGui.QPixmap(side, side)
        canvas.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(canvas)
        try:
            delegate._paint_badges(painter, index, 0, 0, side)
        finally:
            painter.end()
        image = canvas.toImage()

        from amaze.helpers import theme
        badge = delegates.AssetItemDelegate._badge_side(side)
        inset = theme.ui_px(2)
        middle = inset + badge // 2
        far = side - inset - badge // 2
        corners = {
            "badge_open": (middle, middle),
            "badge_star": (far, middle),
            "badge_versions": (middle, far),
            "badge_comment_75": (far, far),
        }
        for name, (x, y) in corners.items():
            self.assertEqual(
                colors[name].rgb(), image.pixel(x, y) | 0xFF000000,
                "%s is not in its own corner - two badges in one corner "
                "hide each other and still look like a badge" % name)
        """Source ban, the scrollbar-stylesheet pattern: the state this
        family replaced was four private rasterisers, three size
        formulas and a colour push - none of the old names may quietly
        return to delegates.py."""
        import inspect
        source = inspect.getsource(delegates)
        for banned in ("_star_pixmap", "_open_pixmap", "_versions_pixmap",
                       "_notes_badge_pixmap", "_notes_badge_side",
                       "OPEN_BADGE_POINTS", "set_star_color",
                       "icon_open_scene", "star_on.svg", "icon_versions"):
            self.assertNotIn(
                banned, source,
                "'%s' is back in delegates.py - the badge family has "
                "been forked" % banned)


class SidebarIndentTest(unittest.TestCase):
    """Every sidebar row reserves the colour strip's width, coloured or not: indenting only coloured rows sat a striped category's label 4px right of its plain neighbours, so the strip is a PLACEHOLDER on every row - coloured rows paint into it, plain rows leave it empty."""

    COLOR_ROLE = int(QtCore.Qt.ItemDataRole.UserRole) + 77

    def _option_for(self, colour):
        """The style option the delegate hands the STYLE for one row - there is no `paint` override to record from, so the strip is a DECORATION declared here and laid out by Qt afterwards, which makes reading the option the same as reading what the row will be."""
        role = self.COLOR_ROLE

        class _Row(QtCore.QAbstractListModel):
            def rowCount(self, parent=QtCore.QModelIndex()):
                return 1

            def data(self, index, r=QtCore.Qt.ItemDataRole.DisplayRole):
                if r == QtCore.Qt.ItemDataRole.DisplayRole:
                    return "Acrylic"
                if r == role:
                    return colour
                return None

        view = QtWidgets.QListView()
        self.addCleanup(view.deleteLater)
        delegate = delegates.SidebarItemDelegate(view)
        delegate.color_role = role
        model = _Row()
        self._model = model                          # keep alive
        option = QtWidgets.QStyleOptionViewItem()
        option.rect = QtCore.QRect(0, 0, 220, 28)
        option.widget = view
        option.font = view.font()
        option.palette = view.palette()
        delegate.initStyleOption(option, model.index(0, 0))
        return option

    def test_plain_and_coloured_rows_start_their_labels_together(self):
        from amaze.helpers import theme
        plain = self._option_for(None)
        strip = self._option_for("#e28248")
        bar = theme.ui_px(4)
        self.assertEqual(   # Qt lays the label out after the decoration, so equal decoration widths ARE labels that start together
            plain.decorationSize, strip.decorationSize,
            "the two rows reserve different widths, so their labels "
            "cannot start at the same x")
        self.assertEqual(
            bar, plain.decorationSize.width(),
            "the reserved strip is not the colour bar's width")
        for option in (plain, strip):
            self.assertTrue(
                option.features
                & QtWidgets.QStyleOptionViewItem.ViewItemFeature.
                HasDecoration,
                "a row does not declare a decoration, so nothing is "
                "reserved on it at all")
        strip_px = strip.icon.pixmap(strip.decorationSize).toImage()  # anti-vacuity both directions: the coloured row's strip really carries the colour, the plain row's really is transparent
        plain_px = plain.icon.pixmap(plain.decorationSize).toImage()
        self.assertEqual(
            QtGui.QColor("#e28248").rgb(),
            strip_px.pixelColor(0, 0).rgb(),
            "the coloured row's strip is not painted in its colour")
        self.assertEqual(
            0, plain_px.pixelColor(0, 0).alpha(),
            "the plain row's placeholder is filled - it reserves the "
            "width but must stay empty")


class OnePickerForTheWholeAppTest(unittest.TestCase):
    """pick_color decides Houdini-vs-Qt at call time; headless has no hou.ui, so these exercise the decision and the Qt path while the native path stays a live check by design."""

    def test_headless_takes_the_qt_path_and_respects_cancel(self):
        from unittest.mock import patch
        from amaze.helpers import ui_helpers
        from PySide6 import QtGui, QtWidgets

        with patch.object(QtWidgets.QColorDialog, "getColor",
                          return_value=QtGui.QColor()) as picker:
            self.assertIsNone(ui_helpers.pick_color("#112233"))
        picker.assert_called_once()

    def test_a_chosen_colour_comes_back_as_qcolor(self):
        from unittest.mock import patch
        from amaze.helpers import ui_helpers
        from PySide6 import QtGui, QtWidgets

        with patch.object(QtWidgets.QColorDialog, "getColor",
                          return_value=QtGui.QColor("#589abb")):
            picked = ui_helpers.pick_color("#112233")
        self.assertEqual("#589abb", picked.name())

    def test_no_direct_qcolordialog_call_sites_remain(self):
        """Source-derived: one helper means behaviour decided in one place, and a site calling QColorDialog directly silently opts out of the native picker and the modal guard."""
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(
            __import__("amaze.helpers.ui_helpers",
                       fromlist=["x"]).__file__)))
        offenders = []
        for folder, _dirs, files in os.walk(root):
            parts = folder.split(os.sep)
            if "tests" in parts or "__pycache__" in parts:
                continue
            for name in files:
                if not name.endswith(".py") or name == "ui_helpers.py":
                    continue
                full = os.path.join(folder, name)
                with open(full, encoding="utf-8") as fh:
                    if "QColorDialog" in fh.read():
                        offenders.append(os.path.relpath(full, root))
        self.assertEqual([], offenders,
                         "these call QColorDialog directly instead of "
                         "ui_helpers.pick_color: %s" % offenders)


class TheSubtitleIsTheNAMEsSize(unittest.TestCase):
    """A tile's sub-line takes the NAME's size, and is secondary by COLOUR alone: an ABSOLUTE 12pt floor on the sub-line against a name drawn at the option font's own size made the secondary text LARGER than the thing it describes - measured at a 9pt Houdini UI font on Windows, with a view not inheriting the panel's floored font, the name comes out 9pt and the subtitle 12pt, while a ~13pt macOS UI font never engages the floor, so the fields read as mismatched on Windows and fine on a Mac for the whole life of the code."""

    def test_the_two_sizes_match_at_every_ui_font(self):
        for point_size in (9.0, 10.0, 11.0, 12.0, 13.0, 16.0):
            with self.subTest(ui_font=point_size):
                base = QtGui.QFont("Source Sans 3")
                base.setPointSizeF(point_size)
                name, rend, _fn, _fr = delegates.AssetItemDelegate.fonts_for(
                    base, False)
                self.assertAlmostEqual(
                    name.pointSizeF(), rend.pointSizeF(), places=2,
                    msg="at a %.1fpt UI font the name is %.1f and the "
                        "subtitle %.1f - one row, two sizes"
                        % (point_size, name.pointSizeF(),
                           rend.pointSizeF()))

    def test_it_holds_when_selected_too(self):
        """Selection bolds both; it must not resize either."""
        base = QtGui.QFont("Source Sans 3")
        base.setPointSizeF(9.0)
        plain = delegates.AssetItemDelegate.fonts_for(base, False)
        picked = delegates.AssetItemDelegate.fonts_for(base, True)
        self.assertAlmostEqual(picked[0].pointSizeF(),
                               picked[1].pointSizeF(), places=2)
        self.assertAlmostEqual(plain[0].pointSizeF(),
                               picked[0].pointSizeF(), places=2,
                               msg="selecting a row changed its size")

    def test_no_absolute_point_size_is_floored_in_the_delegate(self):
        """Read as STRUCTURE: a magic pt literal is a rule that can only be right on the machine it was typed on."""
        import inspect
        import re
        source = inspect.getsource(delegates.AssetItemDelegate.fonts_for)
        magic = re.findall(r"setPointSizeF\([^)]*\b\d+\.?\d*\b[^)]*\)",
                           source)
        self.assertEqual(
            [], [m for m in magic if "pointSizeF()" not in m],
            "a hard-coded point size is back in fonts_for: %s" % magic)

    def test_a_PIXEL_sized_option_font_still_derives(self):
        """A view whose font is set in PIXELS answers -1 to `pointSizeF`, and Qt refuses that as a size - so the derivation is dropped, loudly, once per cache miss."""
        delegates.AssetItemDelegate._font_cache.clear()
        self.addCleanup(delegates.AssetItemDelegate._font_cache.clear)
        base = QtGui.QFont("Source Sans 3")
        base.setPixelSize(9)
        refused = []
        QtCore.qInstallMessageHandler(
            lambda mode, ctx, message: refused.append(message))
        self.addCleanup(QtCore.qInstallMessageHandler, None)
        name, rend, fm_name, fm_rend = \
            delegates.AssetItemDelegate.fonts_for(base, False)
        QtCore.qInstallMessageHandler(None)
        self.assertEqual(
            [], [line for line in refused if "setPointSizeF" in line],
            "the sub-line handed Qt a size it refuses")
        self.assertEqual(9, rend.pixelSize(),
                         "the sub-line left the option font's pixel size")
        self.assertEqual(name.pixelSize(), rend.pixelSize(),
                         "one row, two sizes")
        self.assertEqual(fm_name.height(), fm_rend.height(),
                         "the two lines measure differently")


if __name__ == "__main__":
    unittest.main()
