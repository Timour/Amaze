"""Delegate painting contracts: Qt paints every visible item with one shared painter."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(   # three dirnames up is scripts/python: the dev tree, not the install
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # before the app exists ▸p/first-app-picks-the-platform
from PySide6 import QtCore, QtGui, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401
from amaze import amazetheme  # noqa: E402
from amaze.core import renderers  # noqa: E402
from amaze.panel import delegates  # noqa: E402
from amaze.tests import test_support  # noqa: E402 - redirects the debug log


class _ExplodingModel(QtCore.QAbstractListModel):
    """Row 1 raises, as a real row does when it vanishes between layout and paint."""

    def __init__(self, only_role=None):
        super().__init__()
        self._only_role = only_role  # raise only for this role, to fail late in _paint, after pens and fonts are set

    def rowCount(self, parent=None):
        return 3

    def data(self, index, role=0):
        if index.row() == 1 and (
                self._only_role is None or role == self._only_role):
            raise IndexError("list index out of range")
        return "row %d" % index.row()


class TheTileStandsOnItsFrame(unittest.TestCase):
    """The tile's cell and every badge land where the T frames draw them. ▸r/tile-from-frame"""

    def setUp(self):
        from amaze import amazetheme
        from amaze.helpers import theme
        self.px = theme.ui_px
        self.layout = amazetheme.DIALOG_LAYOUT
        self.frame = amazetheme.DIALOG_LAYOUT["T01"]
        self.node = {kind: amazetheme.drawn_node("T01", kind)
                     for kind in ("thumbnail", "tile name", "tile subtitle")}
        self.size = amazetheme.TILE_DRAWN_SIZE
        self.D = delegates.AssetItemDelegate

    def _drawn(self, badge):
        """Where a T frame draws this badge, found by its name."""
        from amaze import amazetheme
        for key in sorted(k for k in self.layout if k.startswith("T")):
            for node in amazetheme.drawn_nodes(key, "badge " + badge.name):
                return tuple(self.px(n) for n in node[1:5])
        self.fail("no T frame draws the %s badge" % badge.name)

    def test_the_cell_is_the_frame(self):
        font = QtGui.QFont()
        _nf, _rf, fm_name, fm_sub = self.D.fonts_for(font, False)
        drawn_text = self.node["tile name"][4] + self.node["tile subtitle"][4]
        width, height = self.frame["frame"]
        cell = self.D.grid_cell_size(self.size, font)
        self.assertEqual(self.px(width), cell.width())
        self.assertEqual(    # the text block is the font's own height, not the drawing's
            self.px(height) - self.px(drawn_text) + fm_name.height() + fm_sub.height(),
            cell.height())

    def test_every_badge_is_clicked_on_its_drawn_corner(self):
        width, height = self.frame["frame"]
        rect = QtCore.QRect(0, 0, self.px(width), self.px(height))
        for badge in delegates.BADGES:
            with self.subTest(badge=badge.name):
                got = self.D._badge_rect(self.D.__new__(self.D), rect, badge.name)
                self.assertEqual(self._drawn(badge),
                                 (got.x(), got.y(), got.width(), got.height()))

    def test_a_badge_drawn_in_two_places_refuses(self):
        """Two frames disagreeing on a badge's place is a document error, not a choice."""
        from unittest import mock
        from amaze import amazetheme
        moved = dict(self.layout["T08"])
        moved["nodes"] = tuple(
            ("badge open (top-left) ▸ badge_open", 9, 6, 22, 22, None)
            if n[0].startswith("badge open (") else n for n in moved["nodes"])
        with mock.patch.dict(amazetheme.DIALOG_LAYOUT, {"T99": moved}):
            with self.assertRaises(ValueError):
                amazetheme.drawn_badges()

    def test_a_badge_is_placed_by_its_own_inset_on_each_axis(self):
        """Each badge carries two insets of its own; nothing assumes the corners agree."""
        delegate = self.D.__new__(self.D)
        delegate.PLACES = {"open": ("end", 5, "start", 7, 18)}
        side = self.D._badge_side(130, 18)
        self.assertEqual((10 + 130 - side - 5, 20 + 7, side, side),
                         delegate._badge_at("open", 10, 20, 130))

    def test_a_badge_across_the_middle_is_centred_and_scales_with_the_tile(self):
        """The run button is drawn across the thumbnail's middle: it stays there at any size."""
        from unittest import mock
        from amaze import amazetheme
        for badge, expected in (
                (("badge open (top-left) ▸ badge_open", 107, 105, 22, 22, None),
                 {"open": ("end", 5, "end", 7, 22)}),
                (("badge execute (centre) ▸ badge_execute", 51, 55, 36, 36, None),
                 {"execute": ("centre", 0.0, "centre", 4.0, 36)})):
            frame = {"frame": (138, 177), "nodes": (
                ("thumbnail", 4, 4, 130, 130, None), badge)}
            with self.subTest(badge=badge[0]), mock.patch.dict(
                    amazetheme.DIALOG_LAYOUT, {"T01": frame}, clear=True):
                self.assertEqual(expected, amazetheme.drawn_badges(),
                                 "a badge does not measure from the side "
                                 "it is drawn on")
        delegate = self.D.__new__(self.D)
        delegate.PLACES = {"execute": ("centre", 0.0, "centre", 4.0, 36)}
        self.assertEqual((51, 55, 36, 36), delegate._badge_at("execute", 4, 4, 130))
        x, y, w, _h = delegate._badge_at("execute", 0, 0, 65)
        self.assertEqual((23, 25, 18), (x, y, w),
                         "at half the tile the button is half as big and still centred")

    def test_every_badge_is_painted_on_its_drawn_corner(self):
        """The paint loop places badges with its own maths, apart from the click rect."""
        roles, values = {}, {}    # one number per role NAME, holding the value that turns it on
        for i, b in enumerate(delegates.BADGES):
            if b.role:
                role = roles.setdefault(b.role, QtCore.Qt.ItemDataRole.UserRole + 70 + i)
                values.setdefault(role, b.minimum or b.equals or True)

        class _Model(QtCore.QAbstractListModel):
            def rowCount(self, parent=QtCore.QModelIndex()):
                return 1

            def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
                return values.get(role)

        painted = []

        class _Recorder(QtGui.QPainter):
            def drawPixmap(self, x, y, mark):
                painted.append((x, y, mark.width(), mark.height()))

        original = self.D.__dict__["_badge_pixmap"]
        self.D._badge_pixmap = staticmethod(
            lambda art, side, dpr=1.0, opacity=None: QtGui.QPixmap(side, side))
        self.addCleanup(setattr, self.D, "_badge_pixmap", original)

        _kind, x, y, w, h, _text = self.node["thumbnail"]
        model = _Model()
        surface = QtGui.QPixmap(self.px(x + w), self.px(y + h))
        painter = _Recorder(surface)
        try:
            test_support.tile_delegate(
                {b.name: roles.get(b.role) for b in delegates.BADGES})._paint_badges(
                painter, model.index(0, 0), self.px(x), self.px(y), self.px(w))
            values[roles["RendererRole"]] = renderers.ALL[0].key
            test_support.tile_delegate({"renderer": roles["RendererRole"]})._paint_badges(
                painter, model.index(0, 0), self.px(x), self.px(y), self.px(w))
        finally:
            painter.end()
        self.assertEqual([self._drawn(b) for b in delegates.BADGES], painted)


class TheColourSwapIgnoresCase(unittest.TestCase):
    """Figma writes `#5CC9F5`; a tint keyed `#5cc9f5` must still find it."""

    def test_a_lowercase_key_recolours_capital_hex(self):
        import tempfile
        from amaze.helpers import ui_helpers
        folder = tempfile.mkdtemp(prefix="amaze_tint_")
        self.addCleanup(__import__("shutil").rmtree, folder, ignore_errors=True)
        path = os.path.join(folder, "capital.svg")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('<svg width="8" height="8" viewBox="0 0 8 8" '
                         'xmlns="http://www.w3.org/2000/svg">'
                         '<rect width="8" height="8" fill="#5CC9F5"/></svg>')
        image = ui_helpers.render_svg_pixmap(path, 8, {"#5cc9f5": "#ff0000"}).toImage()
        self.assertEqual("#ff0000", image.pixelColor(4, 4).name())


class TheSvgCacheTest(unittest.TestCase):
    """An icon is read, parsed and rastered once; here because a QPixmap needs a QApplication."""

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
        self.ui_helpers.render_svg_pixmap(
            self.icon, 32, {"#5d7abd": "#ff0000"})
        self.assertEqual(
            2, len(self.ui_helpers._SVG_CACHE),
            "a tinted render reused the untinted picture")
        self.ui_helpers.render_svg_pixmap(self.icon, 64)
        self.assertEqual(3, len(self.ui_helpers._SVG_CACHE),
                         "another size reused the 32px picture")

    def test_the_caller_never_receives_the_cached_pixmap_itself(self):
        """QPixmap is mutable: a caller painting into the cached object would poison every later ask."""
        first = self.ui_helpers.render_svg_pixmap(self.icon, 32)
        second = self.ui_helpers.render_svg_pixmap(self.icon, 32)
        self.assertIsNot(first, second)
        cached = self.ui_helpers._SVG_CACHE[(self.icon, 32, (), None)]
        self.assertIsNot(first, cached)


class OneSvgPainterTest(unittest.TestCase):
    """`paint_svg` draws what each hand-written render it replaced drew, antialias hint or none."""

    @staticmethod
    def _by_hand(device, svg, antialias):
        from PySide6 import QtSvg
        renderer = QtSvg.QSvgRenderer(
            QtCore.QByteArray(svg) if isinstance(svg, bytes) else svg)
        device.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(device)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, antialias)
        renderer.render(painter)
        painter.end()
        return device

    @staticmethod
    def _image(device):
        return device.toImage() if isinstance(device, QtGui.QPixmap) else device

    def test_every_device_and_source_matches_the_copies_it_replaced(self):
        from amaze.helpers import ui_helpers
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "ui", "badge_favourite.svg")
        with open(path, "rb") as handle:
            text = handle.read()
        devices = {
            "ARGB32": lambda: QtGui.QImage(48, 48, QtGui.QImage.Format.Format_ARGB32),
            "premultiplied": lambda: QtGui.QImage(
                48, 48, QtGui.QImage.Format.Format_ARGB32_Premultiplied),
            "pixmap": lambda: QtGui.QPixmap(48, 48),
        }
        for source in (path, text):
            for kind, make in devices.items():
                for antialias in (False, True):
                    with self.subTest(source=type(source).__name__, device=kind,
                                      antialias=antialias):
                        want = self._image(self._by_hand(make(), source, antialias))
                        got = make()
                        self.assertTrue(ui_helpers.paint_svg(got, source))
                        self.assertEqual(want, self._image(got))

    def test_unreadable_art_answers_false_and_leaves_the_device_clear(self):
        from amaze.helpers import ui_helpers
        image = QtGui.QImage(8, 8, QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtGui.QColor("#ff0000"))
        self.assertFalse(ui_helpers.paint_svg(image, b"<not an svg"))
        self.assertEqual(0, image.pixelColor(4, 4).alpha())

    def test_the_about_logo_artboard_matches_its_antialiased_render(self):
        from amaze.helpers import ui_helpers
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "ui", "logo.svg")
        make = lambda: QtGui.QImage(1024, 512, QtGui.QImage.Format.Format_ARGB32)  # noqa: E731
        want = self._by_hand(make(), path, True)
        got = make()
        self.assertTrue(ui_helpers.paint_svg(got, path))
        self.assertEqual(want, got)

    def test_only_ui_helpers_builds_an_svg_renderer(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        offenders = []
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__")]
            for name in files:
                full = os.path.join(folder, name)
                if not name.endswith(".py") or full.endswith(
                        os.path.join("helpers", "ui_helpers.py")):
                    continue
                with open(full, encoding="utf-8") as handle:
                    if "QSvgRenderer" in handle.read():
                        offenders.append(os.path.relpath(full, root))
        self.assertEqual([], offenders,
                         "these render SVG by hand instead of through "
                         "`ui_helpers.paint_svg`")


class PainterBalanceTest(unittest.TestCase):
    """A delegate hands the painter back as it got it, even when a row raises mid-paint."""

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
        """Paint one row and end the painter; returns pen colour and font size before and after."""
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
            pass  # the fallback super().paint() re-reads the bad row and raises too

        after = (painter.pen().color().name(), painter.font().pointSize())
        painter.end()
        return before, after

    def test_a_failing_tile_leaves_the_save_stack_balanced(self):
        before, after = self._paint_row(_ExplodingModel(), 0)
        self.assertEqual(before, after, "a healthy tile leaked its pen/font")
        self._paint_row(_ExplodingModel(), 1)
        unbalanced = [m for m in self.messages if "saved states" in m]
        self.assertEqual(
            [], unbalanced,
            "the delegate left the shared painter with an unbalanced save "
            "stack; every row painted after it inherits the leaked state")

    def test_no_pen_or_font_leaks_however_late_the_failure(self):
        """Raising on the last role read: `_paint` reads every role before its first setPen."""
        model = _ExplodingModel(
            only_role=QtCore.Qt.ItemDataRole.UserRole + 3)
        before, after = self._paint_row(model, 1)
        self.assertEqual(
            before, after,
            "a failing tile left its pen/font on the shared painter")


class _RectSpy(QtGui.QPainter):
    """Records every fillRect, so the card extent is measured rather than inferred from pixels."""

    def __init__(self, device):
        super().__init__(device)
        self.rects = []

    def fillRect(self, *args):
        if args and isinstance(args[0], QtCore.QRect):
            self.rects.append(QtCore.QRect(args[0]))
        return super().fillRect(*args)


class CardFillsItsCellTest(unittest.TestCase):
    """A tile with no subtitle fills its cell: `grid_cell_size` reserves both text heights."""

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
        view.setViewMode(QtWidgets.QListView.ViewMode.IconMode)  # IconMode is the grid; a default QListView is in ListMode
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
        self.assertGreaterEqual(
            without, without_h - 1,
            "the card stops %dpx short of its own cell"
            % (without_h - 1 - without))


class BandContrastTest(unittest.TestCase):
    """A category colour never makes its own label unreadable; #00ee00 is the case to watch."""

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

    LEGACY_PRESETS = ("#ef8878", "#4af2a1", "#5cc9f5", "#e2b148")   # what older saved tiles hold; the live palette is drawn, not this corpus

    def test_the_shipped_presets_are_unchanged(self):
        """The contrast rule does not restyle what is saved: the four legacy presets keep their ink."""
        for value in self.LEGACY_PRESETS + ("#00ee00",):    # the green that exposed the old threshold
            color = QtGui.QColor(value)
            self.assertGreater(
                self.DELEGATE.contrast_ratio(
                    color, self.DELEGATE.text_on(color)),
                4.5, "preset %s lost contrast" % value)

    def test_a_dark_category_is_legible_in_list_mode(self):
        """List mode paints the colour as the pen on the row; #333333 measured 1.03:1 against it."""
        row = QtGui.QColor("#2d2d2d")
        for value in ("#333333", "#262626", "#1a1a1a", "#000000"):
            adjusted = self.DELEGATE.readable_on(QtGui.QColor(value), row)
            self.assertGreaterEqual(
                self.DELEGATE.contrast_ratio(adjusted, row), 4.0,
                "%s stays invisible in list mode" % value)
        for value in self.LEGACY_PRESETS:    # already readable: the hue identifies the category
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
        """Each read is a proxy-to-source round trip plus a QColor parse, so the band reuses it."""
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
        """A badge rasterises at side*dpr, as `_icon_pixmap` does, or Retina upscales it soft."""
        normal = delegates.AssetItemDelegate._badge_pixmap(
            "badge_favourite", 22, 1.0)
        retina = delegates.AssetItemDelegate._badge_pixmap(
            "badge_favourite", 22, 2.0)
        if normal.isNull() or retina.isNull():
            self.skipTest("badge_favourite.svg not resolvable outside an install")
        self.assertEqual(
            44, retina.width(),
            "the Retina badge is still rasterised at logical size")
        self.assertAlmostEqual(2.0, retina.devicePixelRatio(), places=3)
        self.assertNotEqual(normal.cacheKey(), retina.cacheKey())  # and the two must not share a cache entry

    def test_badge_placement_uses_logical_size(self):
        """width() is physical pixels once devicePixelRatio is set, so placement uses logical size."""
        retina = delegates.AssetItemDelegate._badge_pixmap(
            "badge_favourite", 22, 2.0)
        if retina.isNull():
            self.skipTest("badge_favourite.svg not resolvable outside an install")
        logical_w, _h = delegates.AssetItemDelegate._logical_size(retina)
        self.assertEqual(
            22, logical_w,
            "the logical size helper disagrees with the rendered badge")
        self.assertNotEqual(
            logical_w, retina.width(),
            "this test proves nothing unless the two differ")


class BadgeFamilyTest(unittest.TestCase):
    """The four badges are one family: one art set, `_badge_pixmap`, `_badge_side`, no re-tint."""

    NAMES = ("badge_open", "badge_favourite", "badge_favourite_off", "badge_versions",
             "badge_comment", "badge_edit") + tuple(r.badge for r in renderers.ALL)

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
        """Wire one badge role, run `_paint_badges`, and record every rasteriser ask with its dpr."""
        asked = []

        def spy(name, side, dpr=1.0, opacity=None):
            asked.append((name, side, dpr, opacity))
            return QtGui.QPixmap()          # null - nothing is drawn

        role = QtCore.Qt.ItemDataRole.UserRole + 77

        class _RoleModel(QtCore.QAbstractListModel):
            def rowCount(self, parent=QtCore.QModelIndex()):
                return 1

            def data(self, index, r=QtCore.Qt.ItemDataRole.DisplayRole):
                return value if r == role else None

        delegate = test_support.tile_delegate({role_kw: role})
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
        """Each corner asks for its own art by name, at the `_badge_side` size and the real dpr."""
        corner = delegates.AssetItemDelegate._badge_side(128)
        rest = amazetheme.BADGE_REST_OPACITY
        cases = (    # (badge, its value, art, size, opacity: None = as drawn)
            ("open", True, "badge_open", corner, None),
            ("favourite", True, "badge_favourite", corner, None),
            ("versions", 3, "badge_versions", corner, rest),
            ("comment", True, "badge_comment", corner, rest),
            ("execute", "Python", "badge_execute", min(45, round(45 * 128 / 130.0)), None),
            ("edit", True, "badge_edit", corner, rest),
            ("renderer", "Redshift", "badge_renderer_redshift", corner, None),
        )
        self.assertEqual(
            len(cases), len(delegates.BADGES),
            "the badge table and this test disagree about how many "
            "badges there are - a new row must be driven here too")
        for role_kw, value, art, expected, opacity in cases:
            asked = self._asked_for(role_kw, value, 128)
            self.assertEqual(
                [(art, expected, 2.0, opacity)], asked,
                "%s does not go through the family engine, or the pass "
                "asked for a badge nothing wired" % role_kw)

    def test_the_renderer_badge_draws_each_renderers_own_art(self):
        """One badge per renderer, from the renderer table; an older spelling finds its renderer."""
        corner = delegates.AssetItemDelegate._badge_side(128)
        cases = [(r.key, r.badge) for r in renderers.ALL] + [("MaterialX", "badge_renderer_materialx")]
        for stored, art in cases:
            with self.subTest(renderer=stored):
                self.assertEqual([(art, corner, 2.0, None)],
                                 self._asked_for("renderer", stored, 128))
        self.assertEqual([], self._asked_for("renderer", "Cycles", 128),
                         "a renderer Amaze does not offer drew a badge")

    def test_every_button_badge_wears_the_one_rest_and_hover_opacity(self):
        """Every button badge rests at the one strength; under the pointer its hover art wins."""
        role = QtCore.Qt.ItemDataRole.UserRole + 66
        family = {b.name for b in delegates.BADGES if b.dims or b.off_art}
        self.assertEqual({"favourite", "versions", "comment", "edit"}, family)
        cases = (("favourite", False), ("versions", 3), ("comment", True),
                 ("comment", False), ("edit", True))
        current = {}

        class _Model(QtCore.QAbstractListModel):
            def rowCount(self, parent=QtCore.QModelIndex()):
                return 1

            def data(self, index, r=QtCore.Qt.ItemDataRole.DisplayRole):
                return current.get("value") if r == role else None

        asked = []
        cls = delegates.AssetItemDelegate
        original = cls.__dict__["_badge_pixmap"]
        cls._badge_pixmap = staticmethod(
            lambda name, side, dpr=1.0, opacity=None: asked.append((name, opacity))
            or QtGui.QPixmap())
        self.addCleanup(setattr, cls, "_badge_pixmap", original)
        model = _Model()
        index = model.index(0, 0)
        for rest, hover in ((0.4, 0.75), (0.3, 0.9)):
            with mock.patch.object(amazetheme, "BADGE_REST_OPACITY", rest), \
                    mock.patch.object(amazetheme, "BADGE_HOVER_OPACITY", hover):
                for name, value in cases:
                    current["value"] = value
                    badge = delegates.BADGE[name]
                    art = badge.off_art if value is False else badge.art
                    drawn = badge.off_hover_art if value is False else badge.hover_art
                    for hovered, want in ((False, (art, rest)),
                                          (True, (drawn, None) if drawn else (art, hover))):
                        delegate = test_support.tile_delegate({name: role})
                        delegate.set_badge_click(name, lambda index: None)
                        if hovered:
                            delegate.set_button_hover(name, index)
                        asked.clear()
                        surface = QtGui.QPixmap(140, 140)
                        painter = QtGui.QPainter(surface)
                        try:
                            delegate._paint_badges(painter, index, 0, 0, 130)
                        finally:
                            painter.end()
                        self.assertEqual([want], asked,
                                         "%s at %s" % (name, "hover" if hovered else "rest"))

    def test_the_opacity_reaches_every_part_of_the_art(self):
        """Ground and icon alike take the state's strength, read off the rendered pixels."""
        for name in ("badge_favourite_off", "badge_versions", "badge_comment",
                     "badge_comment_off", "badge_edit"):
            for opacity in (0.4, 0.75):
                image = delegates.AssetItemDelegate._badge_pixmap(
                    name, 44, 1.0, opacity).toImage()
                if image.isNull():
                    self.skipTest("%s.svg not resolvable outside an install" % name)
                ground = image.pixelColor(22, 3).alpha()    # the dark ground, clear of the icon
                self.assertAlmostEqual(opacity * 255, ground, delta=3,
                                       msg="%s ground at %s" % (name, opacity))


class SidebarIndentTest(unittest.TestCase):
    """Every sidebar row reserves the colour strip width, coloured or not, so labels line up."""

    COLOR_ROLE = int(QtCore.Qt.ItemDataRole.UserRole) + 77

    def _option_for(self, colour):
        """The style option the delegate hands the style for one row; the strip is its decoration."""
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
        self.assertEqual(   # Qt lays the label out after the decoration, so equal widths align labels
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
        strip_px = strip.icon.pixmap(strip.decorationSize).toImage()  # anti-vacuity: the coloured strip carries the colour, the plain one is clear
        plain_px = plain.icon.pixmap(plain.decorationSize).toImage()
        self.assertEqual(
            QtGui.QColor("#e28248").rgb(),
            strip_px.pixelColor(0, 0).rgb(),
            "the coloured row's strip is not painted in its colour")
        self.assertEqual(
            0, plain_px.pixelColor(0, 0).alpha(),
            "the plain row's placeholder is filled - it reserves the "
            "width but must stay empty")


class HiddenCountsAreStillFetched(unittest.TestCase):
    """With counts off every row's count is still asked, and only All shows its count."""

    def _counted(self, show_counts):
        from amaze.core import category
        asked = []

        class _Rows(QtCore.QAbstractListModel):
            def rowCount(self, parent=QtCore.QModelIndex()):
                return 2

            def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
                if role == QtCore.Qt.ItemDataRole.DisplayRole:
                    return ("All", "Wood")[index.row()]
                if role == category.SIDEBAR_COUNT_ROLE:
                    asked.append(index.row())
                    return 3
                return None

        view = QtWidgets.QListView()
        self.addCleanup(view.deleteLater)
        delegate = delegates.SidebarItemDelegate(view)
        delegate.show_counts = show_counts
        model = _Rows()
        texts = []
        for row in range(2):
            option = QtWidgets.QStyleOptionViewItem()
            option.widget = view
            option.font = view.font()
            delegate.initStyleOption(option, model.index(row, 0))
            texts.append(option.text)
        return asked, texts

    def test_off_still_asks_every_row_and_shows_only_all(self):
        for show, shown in ((False, ["All (3)", "Wood"]),
                            (True, ["All (3)", "Wood (3)"])):
            with self.subTest(show_counts=show):
                asked, texts = self._counted(show)
                self.assertEqual(shown, texts)
                self.assertEqual([0, 1], asked, "a count went unfetched")


class OnePickerForTheWholeAppTest(unittest.TestCase):
    """`pick_color` picks Houdini or Qt at call time; headless has no hou.ui, so the Qt path runs."""

    def test_headless_takes_the_qt_path_and_respects_cancel(self):
        from unittest.mock import patch
        from amaze.helpers import ui_helpers
        from PySide6 import QtGui, QtWidgets

        with patch.object(QtWidgets.QColorDialog, "getColor",
                          return_value=QtGui.QColor()):
            self.assertIsNone(ui_helpers.pick_color("#112233"),
                              "a cancelled pick answered a colour")
        with patch.object(QtWidgets.QColorDialog, "getColor",
                          return_value=QtGui.QColor("#589abb")):
            picked = ui_helpers.pick_color("#112233")
        self.assertEqual("#589abb", picked.name())

    def test_no_direct_qcolordialog_call_sites_remain(self):
        """A direct QColorDialog call skips the native picker and the modal guard."""
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(
            __import__("amaze.helpers.ui_helpers",
                       fromlist=["x"]).__file__)))
        offenders = []
        for folder, _dirs, files in os.walk(root):
            parts = os.path.relpath(folder, root).split(os.sep)
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
    """The sub-line takes the name size, secondary by colour alone, at every UI font size."""

    def test_the_two_sizes_match_at_every_ui_font(self):
        """Selection bolds both; it must not resize either."""
        for point_size in (9.0, 10.0, 11.0, 12.0, 13.0, 16.0):
            for selected in (False, True):
                with self.subTest(ui_font=point_size, selected=selected):
                    base = QtGui.QFont("Source Sans 3")
                    base.setPointSizeF(point_size)
                    name, rend, _fn, _fr = \
                        delegates.AssetItemDelegate.fonts_for(base, selected)
                    plain = delegates.AssetItemDelegate.fonts_for(base, False)
                    self.assertAlmostEqual(
                        name.pointSizeF(), rend.pointSizeF(), places=2,
                        msg="at a %.1fpt UI font the name is %.1f and the "
                            "subtitle %.1f - one row, two sizes"
                            % (point_size, name.pointSizeF(),
                               rend.pointSizeF()))
                    self.assertAlmostEqual(plain[0].pointSizeF(),
                                           name.pointSizeF(), places=2,
                                           msg="selecting a row changed "
                                               "its size")

    def test_a_PIXEL_sized_option_font_still_derives(self):
        """A pixel-sized font answers -1 to `pointSizeF`, which Qt refuses as a size ▸r/font-sizing"""
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


class TheFontCacheTellsFontsApart(unittest.TestCase):
    """`fonts_for` shares fonts: fonts differing in anything drawn get their own entry ▸r/font-sizing"""

    def _isolated_cache(self):
        delegates.AssetItemDelegate._font_cache.clear()
        self.addCleanup(delegates.AssetItemDelegate._font_cache.clear)

    @staticmethod
    def _at_pixel_size(pixels):
        font = QtGui.QFont("Source Sans 3")
        font.setPixelSize(pixels)
        return font

    def test_two_pixel_sizes_do_not_collide(self):
        self._isolated_cache()
        small = delegates.AssetItemDelegate.fonts_for(
            self._at_pixel_size(9), False)
        large = delegates.AssetItemDelegate.fonts_for(
            self._at_pixel_size(13), False)
        self.assertEqual(9, small[0].pixelSize(),
                         "the 9px caller lost its own size")
        self.assertEqual(13, large[0].pixelSize(),
                         "a 13px option font was served the 9px cache "
                         "entry - every pixel font keys the same")
        self.assertEqual(13, large[1].pixelSize(),
                         "the sub-line was served the 9px cache entry")
        self.assertGreater(large[2].height(), small[2].height(),
                           "both sizes measure the same, so the tile "
                           "lays out at the wrong height too")
        upright = QtGui.QFont("Source Sans 3")
        upright.setPointSizeF(12.0)
        slanted = QtGui.QFont(upright)
        slanted.setItalic(True)
        plain = delegates.AssetItemDelegate.fonts_for(upright, False)
        oblique = delegates.AssetItemDelegate.fonts_for(slanted, False)
        self.assertFalse(plain[0].italic())
        self.assertTrue(oblique[0].italic(),
                        "an italic option font was served the upright "
                        "cache entry - the key ignores style")

    def test_two_weights_do_not_collide(self):
        """On the sub-line: `setBold(True)` sets weight 700, overwriting heavier weights on the name."""
        self._isolated_cache()
        regular = QtGui.QFont("Source Sans 3")
        regular.setPointSizeF(12.0)
        black = QtGui.QFont(regular)
        black.setWeight(QtGui.QFont.Weight.Black)
        plain = delegates.AssetItemDelegate.fonts_for(regular, False)
        heavy = delegates.AssetItemDelegate.fonts_for(black, False)
        self.assertEqual(QtGui.QFont.Weight.Normal, plain[1].weight())
        self.assertEqual(QtGui.QFont.Weight.Black, heavy[1].weight(),
                         "a Black option font was served the regular "
                         "cache entry - the key ignores weight")

    def test_it_is_still_a_CACHE(self):
        """Two separately built but equal fonts land on one entry, or every repaint rebuilds them."""
        self._isolated_cache()
        first = delegates.AssetItemDelegate.fonts_for(
            self._at_pixel_size(11), False)
        second = delegates.AssetItemDelegate.fonts_for(
            self._at_pixel_size(11), False)
        self.assertIs(first, second, "an equal font missed the cache")
        self.assertEqual(1, len(delegates.AssetItemDelegate._font_cache))
        selected = delegates.AssetItemDelegate.fonts_for(
            self._at_pixel_size(11), True)
        self.assertIsNot(first, selected,
                         "selection shares the unselected entry")


if __name__ == "__main__":
    unittest.main()
