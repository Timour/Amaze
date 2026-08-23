"""List mode: badges become COLUMNS, and the slider stops pretending. A list row is one text line tall with a 16px thumbnail, and a 12px badge on a 16px picture covers most of what it annotates - so list mode draws no badges and the four facts they carry (Favorite, Version, Open, Notes) become columns; Version gains the room to say WHICH version. The marks are ticks, not the words true/false. Grid runs 64-512 with a magnet at 128; a list row does not scale, so the slider greys there. These tests PAINT - an earlier badge test asserted a method body mentioned a variable and stayed green through a sabotage that deleted the code using it (practice.md), so nothing here trusts a constant or a flag: a row is rendered and the pixels read back."""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

import test_support  # noqa: E402
from amaze.core import gradient_library  # noqa: E402
from amaze.helpers import theme, ui_helpers  # noqa: E402
from amaze.core import grid_columns
from amaze.panel import delegates, grid  # noqa: E402


FAV_ROLE = QtCore.Qt.ItemDataRole.UserRole + 60
OPEN_ROLE = QtCore.Qt.ItemDataRole.UserRole + 61
NOTE_ROLE = QtCore.Qt.ItemDataRole.UserRole + 62
VERSIONS_ROLE = QtCore.Qt.ItemDataRole.UserRole + 63
ACTIVE_ROLE = QtCore.Qt.ItemDataRole.UserRole + 64
SUBTITLE_ROLE = QtCore.Qt.ItemDataRole.UserRole + 65

ROW_W = 900
ROW_H = 24
THUMB_W = theme.ui_px(30)
NAME_W = theme.ui_px(200)
TYPE_W = theme.ui_px(80)
FAV_W = theme.ui_px(70)
VERSION_W = theme.ui_px(90)
OPEN_W = theme.ui_px(60)
NOTE_W = theme.ui_px(60)


class ListRowPainting(unittest.TestCase):
    """Render one tile and read it back."""

    def setUp(self):
        self.view = QtWidgets.QListView()  # a GRID view: this class rendered LIST rows until the table took list mode, and the delegate has no list branch left
        self.delegate = delegates.AssetItemDelegate(
            SUBTITLE_ROLE,
            favorite_role=FAV_ROLE,
            open_role=OPEN_ROLE,
            notes_role=NOTE_ROLE,
            versions_role=VERSIONS_ROLE,
            active_version_role=ACTIVE_ROLE,
        )

    def _index(self, fav=False, is_open=False, note=False,
               versions=0, active_name=""):
        model = QtGui.QStandardItemModel()
        item = QtGui.QStandardItem("brushed_steel")
        item.setData(fav, FAV_ROLE)
        item.setData(is_open, OPEN_ROLE)
        item.setData(note, NOTE_ROLE)
        item.setData(versions, VERSIONS_ROLE)
        item.setData(active_name, ACTIVE_ROLE)
        item.setData("Karma", SUBTITLE_ROLE)
        model.appendRow(item)
        self._model = model                      # keep alive
        return model.index(0, 0)

    def _render(self, index):
        canvas = QtGui.QPixmap(ROW_W, ROW_H)
        canvas.fill(QtCore.Qt.GlobalColor.black)
        option = QtWidgets.QStyleOptionViewItem()
        option.rect = QtCore.QRect(0, 0, ROW_W, ROW_H)
        option.widget = self.view
        option.font = self.view.font()
        option.palette = self.view.palette()
        painter = QtGui.QPainter(canvas)
        try:
            self.delegate.paint(painter, option, index)
        finally:
            painter.end()
        return canvas.toImage()

    @staticmethod
    def _ink(image, x0, x1):
        """Non-background pixels in a column band, as a set of RGB - column RULES are furniture, not content."""
        rule = (0x45, 0x45, 0x45)  # the old painted strip's divider grey, kept as a literal now the strip is gone; only the grid test uses this reader and it paints no rules
        found = set()
        for x in range(max(0, x0), min(image.width(), x1)):
            for y in range(image.height()):
                rgb = image.pixelColor(x, y)
                value = (rgb.red(), rgb.green(), rgb.blue())
                if value != rule and sum(value) > 40:
                    found.add(value)
        return found

    def _col_x(self, which):
        """Left edge of a mark column, in paint order: ... | Favorite | Version | Open | Notes."""
        base = THUMB_W + NAME_W + TYPE_W
        offsets = {
            "fav": base,
            "version": base + FAV_W,
            "open": base + FAV_W + VERSION_W,
            "note": base + FAV_W + VERSION_W + OPEN_W,
        }
        left = offsets[which]
        width = {"fav": FAV_W, "version": VERSION_W,
                 "open": OPEN_W, "note": NOTE_W}[which]
        return left, left + width

    def _thumb_band(self, image):
        """Every pixel of the thumbnail square, as bytes."""
        return bytes(
            bytearray(
                v
                for x in range(min(THUMB_W, image.width()))
                for y in range(image.height())
                for v in (image.pixelColor(x, y).red(),
                          image.pixelColor(x, y).green(),
                          image.pixelColor(x, y).blue())))

    def test_the_grid_still_gets_its_badges(self):
        """The badges did not go away - they went out of LIST mode; without this, deleting the badge painters entirely would leave every test above green."""
        self.view.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
        canvas = QtGui.QPixmap(160, 190)
        canvas.fill(QtCore.Qt.GlobalColor.black)
        option = QtWidgets.QStyleOptionViewItem()
        option.rect = QtCore.QRect(0, 0, 160, 190)
        option.widget = self.view
        option.font = self.view.font()
        option.palette = self.view.palette()
        def grid_tile(fav):
            canvas.fill(QtCore.Qt.GlobalColor.black)
            painter = QtGui.QPainter(canvas)
            try:
                self.delegate.paint(painter, option, self._index(fav=fav))
            finally:
                painter.end()
            return canvas.toImage().constBits().tobytes()

        self.assertNotEqual(
            grid_tile(True), grid_tile(False),
            "a favourited GRID tile paints the same as an unfavourited "
            "one - the star badge is gone from grid mode too")


class TickIsDrawnNotTyped(unittest.TestCase):
    """U+2713 is missing from fonts Houdini may fall back to, and a missing glyph is an empty box in a column whose whole job is to be a yes - the tick is two drawn lines instead."""

    def test_the_tick_paints_without_any_font(self):
        canvas = QtGui.QPixmap(24, 24)
        canvas.fill(QtCore.Qt.GlobalColor.black)
        painter = QtGui.QPainter(canvas)
        try:
            painter.setFont(QtGui.QFont("A Font That Does Not Exist", 9))
            delegates.AssetItemDelegate._paint_tick(
                painter, QtCore.QRect(0, 0, 24, 24),
                QtGui.QColor("#fcb900"))
        finally:
            painter.end()
        image = canvas.toImage()
        lit = sum(1 for x in range(24) for y in range(24)
                  if image.pixelColor(x, y).red() > 60)
        self.assertGreater(
            lit, 6, "the tick drew nothing - a column whose job is to "
                    "say yes must not depend on a font having the glyph")


class SliderFollowsTheViewMode(unittest.TestCase):
    """Grid scales 64-512 with a magnet at 128; a list row is one text line and does not scale, so the slider is greyed there."""

    def test_the_default_is_the_magnet(self):
        self.assertEqual(
            128, ui_helpers.ClickSlider.DEFAULT_VALUE,
            "the slider's default and its magnet must be the same "
            "number, or the default drags itself off the mark")
        self.assertIn(
            128, ui_helpers.ClickSlider.SNAP_MARKS,
            "128 is the magnet - it has to be in the snap marks")

    def test_the_magnet_pulls_a_near_miss_onto_128(self):
        slider = ui_helpers.ClickSlider()
        slider.setRange(64, 512)
        for start in (128 - ui_helpers.ClickSlider.SNAP_RADIUS + 1,
                      128 + ui_helpers.ClickSlider.SNAP_RADIUS - 1):
            self.assertEqual(
                128, slider._snap(start),
                "a drag ending %s did not snap to the 128 magnet"
                % start)

    def test_a_deliberate_size_is_not_swallowed(self):
        """A magnet that grabs everything is a broken slider - 200 is a size someone chose."""
        slider = ui_helpers.ClickSlider()
        slider.setRange(64, 512)
        self.assertEqual(200, slider._snap(200))


class TheRealPanelInListMode(unittest.TestCase):
    """Against the SHIPPED panel: a view built by the test would pass with the panel broken (the lesson test_grid_scroll records)."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))  # the ISOLATED panel - test_grid_scroll records why _protect_live_settings went

    @classmethod
    def tearDownClass(cls):
        pass  # fixture_panel registers stop_panel_workers and deleteLater through class_scope; a worker destroyed by Py_Finalize aborts hython and the push gate reads the exit as not green

    def _mode(self, mode):
        self.panel.prefs.view_mode = mode
        self.panel.apply_view_mode()
        QtWidgets.QApplication.processEvents()

    def test_the_grid_slider_runs_64_to_512(self):
        self.assertEqual(
            (64, 512),
            (self.panel.click_slider.minimum(),
             self.panel.click_slider.maximum()),
            "a grid tile smaller than 64px is not a tile you can read")

    def test_the_slider_is_dead_in_list_mode(self):
        """A list row is one text line - nothing to scale, so the control says so instead of moving a number nothing reads."""
        self._mode("grid")
        self.assertTrue(self.panel.click_slider.isEnabled(),
                        "the slider should work in grid mode")
        self._mode("list")
        self.assertFalse(
            self.panel.click_slider.isEnabled(),
            "the slider is still live in list mode, where the row size "
            "is fixed - it moves a number nothing reads")
        self.addCleanup(self._mode, "grid")

    def test_list_rows_stay_at_the_smallest_size(self):
        """Whatever the slider last held in grid, list paints its smallest row - list mode displays at the smallest scale only."""
        self._mode("grid")
        self.panel.click_slider.setValue(512)
        QtWidgets.QApplication.processEvents()
        self._mode("list")
        self.addCleanup(self._mode, "grid")
        self.assertEqual(
            self.panel.LIST_THUMB_SIZE, grid.active_thumbsize(self.panel),
            "list mode followed the grid slider instead of staying at "
            "its own smallest size")

    def _columns(self):
        """Every SHOWN column and its width, off the real table - it used to read ten `_list_*_w` attributes the panel pushed into the delegate; there is no push any more, a column is as wide as Qt measures its contents, so this asks the widget that knows."""
        table = self.panel.thumbtable
        return {key: table.columnWidth(column)
                for column, key in enumerate(grid_columns.KEYS)
                if not table.isColumnHidden(column)}

    def _settle(self, width):
        self.panel.resize(width, 600)
        for _ in range(6):
            QtWidgets.QApplication.processEvents()

    def test_narrowing_the_panel_never_drops_a_column(self):
        """Rows collapsed whenever anything took panel width, the notes pane most of all: a row used to be defined as the width of the panel, so the fitting code squeezed columns and then deleted them from the right - nothing about a name or a tag list gets shorter because a pane moved."""
        self._mode("list")
        self.panel.show()
        self.addCleanup(self.panel.hide)
        self.addCleanup(self._mode, "grid")
        self._settle(1200)
        wide = self._columns()
        self.assertTrue(any(wide.values()), "no columns at all - "
                                            "the test is not testing")
        self.assertGreater(len(wide), 3, "too few columns to be testing")
        for width in (900, 640, 460, 380):
            self._settle(width)
            narrow = self._columns()
            lost = [name for name, w in wide.items()
                    if w and not narrow.get(name)]
            self.assertEqual(
                [], lost,
                "at panel width %s the row lost %s - columns are still "
                "being dropped to make the row fit the panel"
                % (width, ", ".join(lost)))

    def test_the_layout_settles_instead_of_oscillating(self):
        """The fear that kept the horizontal scrollbar off for so long, turned into a test: the loop needs the row width to depend on the viewport - it does not any more, so the geometry must hold still with no input."""
        self._mode("list")
        self.panel.show()
        self.addCleanup(self.panel.hide)
        self.addCleanup(self._mode, "grid")
        self._settle(700)
        view = self.panel.thumblist
        seen = set()
        for _ in range(10):
            QtWidgets.QApplication.processEvents()
            seen.add((view.viewport().width(), view.gridSize().width(),
                      view.horizontalScrollBar().maximum()))
        self.assertEqual(
            1, len(seen),
            "the layout is moving with no input - %s distinct states: "
            "%s" % (len(seen), seen))

    def test_list_mode_can_scroll_sideways_and_grid_cannot(self):
        self._mode("list")
        self.addCleanup(self._mode, "grid")
        self.assertNotEqual(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
            self.panel.thumblist.horizontalScrollBarPolicy(),
            "list mode cannot scroll sideways, so a row wider than the "
            "panel is simply unreachable")

    def test_no_column_is_narrower_than_what_it_paints(self):
        """The truncation complaint, pinned: a Version column too narrow for an ordinary version name elides it. Two causes, both removed by construction - columns were MEASURED with the view's font and PAINTED with the delegate's, and the fit sampled rows so a column could be too narrow for a value the sample missed; Qt measures what it draws, in the font it draws it. Asserts the PROPERTY rather than the old floors: every visible cell fits."""
        self._mode("list")
        self.addCleanup(self._mode, "grid")
        self.panel.sync_list_columns()
        QtWidgets.QApplication.processEvents()
        table = self.panel.thumbtable
        proxy = table.model()
        self.assertTrue(proxy.rowCount(), "no rows to measure")
        checked = 0
        for column, key in enumerate(grid_columns.KEYS):
            if table.isColumnHidden(column):
                continue
            width = table.columnWidth(column)  # THE WHOLE COLUMN, no cell padding to subtract: neither Qt's stylesheet examples nor Houdini's base.qss pads an item, and the table wears Houdini's metrics
            for row in range(min(proxy.rowCount(), 25)):
                index = proxy.index(row, column)
                text = index.data(QtCore.Qt.ItemDataRole.DisplayRole)
                if not isinstance(text, str) or not text:
                    continue
                font = index.data(QtCore.Qt.ItemDataRole.FontRole)
                metrics = QtGui.QFontMetrics(font or table.font())
                checked += 1
                self.assertGreaterEqual(
                    width, metrics.horizontalAdvance(text),
                    "the %s column is narrower than %r, which it "
                    "paints - it elides to %s... instead"
                    % (key, text, text[:6]))
        self.assertTrue(checked, "nothing was measured - not a test")

    def test_a_list_row_is_a_text_line_tall(self):
        """A 30px row for one text line is not a list: the row now fits its 16px thumbnail and its text and nothing else - the flat 14px of padding that made it 30 is gone. MEASURED ON THE TABLE, which is what list mode shows: the old read was `_list_grid_size` off the QListView, which is hidden the whole time list mode is up, a number nothing on screen came from - the height that matters is the vertical header's section size."""
        self._mode("list")
        self.addCleanup(self._mode, "grid")
        height = self.panel.thumbtable.verticalHeader().defaultSectionSize()
        fm = QtGui.QFontMetrics(self.panel.thumbtable.font())
        self.assertLessEqual(
            height, max(fm.height(), self.panel.LIST_THUMB_SIZE)
            + theme.ui_px(8),
            "a list row is taller than the things inside it need - "
            "it got %spx for a %spx thumbnail and a %spx text line"
            % (height, self.panel.LIST_THUMB_SIZE, fm.height()))
        self.assertGreaterEqual(
            height, fm.height(),
            "the row is shorter than the text line it paints")

    def test_list_mode_shows_the_table_and_grid_mode_the_list(self):
        """The premise every other list-mode test rests on: two views point at the same model and exactly one is up (grid.show_table) - nothing asserted which, so machinery that sized the HIDDEN one stayed green for as long as it existed. isHidden(), never isVisible(): neither view's window is shown in a headless run, so isVisible() is False for both and the question would answer itself."""
        self._mode("list")
        self.addCleanup(self._mode, "grid")
        self.assertFalse(self.panel.thumbtable.isHidden(),
                         "list mode does not show the table")
        self.assertTrue(self.panel.thumblist.isHidden(),
                        "list mode still shows the QListView - anything "
                        "sizing it is being measured off screen")

        self._mode("grid")
        self.assertTrue(self.panel.thumbtable.isHidden(),
                        "grid mode still shows the table")
        self.assertFalse(self.panel.thumblist.isHidden(),
                         "grid mode does not show the QListView")


class FilteringNeverUnsortsTheList(unittest.TestCase):
    """Pick a category, go back to All, and the list was no longer alphabetical: the proxy runs setDynamicSortFilter(False) for performance, and that switch turns off BOTH halves - no automatic re-sort after a filter change either, so rows returning to view came back in source order; one call site knew (the renderer filter called sort(0) itself), category, search and favourites did not. Tested at the PROXY, where the guarantee now lives - a panel test would prove one section and leave the other four to be found by hand."""

    ROLE = 257  # the proxy matches on the role NUMBERS the sections share - 257 is CategoryRole, expecting the list of categories a material belongs to

    def _proxy(self, names_and_cats):
        from amaze.core import multifilterproxy_model
        model = QtGui.QStandardItemModel()
        for name, cat in names_and_cats:
            item = QtGui.QStandardItem(name)
            item.setData([cat], self.ROLE)
            model.appendRow(item)
        proxy = multifilterproxy_model.MultiFilterProxyModel()
        proxy.setSourceModel(model)
        proxy.setSortCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        proxy.sort(0)
        proxy.setDynamicSortFilter(False)
        self._keep = (model, proxy)
        return proxy

    def _names(self, proxy):
        return [proxy.data(proxy.index(r, 0),
                           QtCore.Qt.ItemDataRole.DisplayRole)
                for r in range(proxy.rowCount())]

    def test_the_list_is_still_sorted_after_a_filter_comes_and_goes(self):
        proxy = self._proxy([
            ("zinc", "metal"), ("Acrylic", "plastic"),
            ("brass", "metal"), ("Aegean", "stone"),
        ])
        self.assertEqual(["Acrylic", "Aegean", "brass", "zinc"],
                         self._names(proxy), "not sorted to begin with")

        proxy.setFilter(self.ROLE, "metal")
        self.assertEqual(["brass", "zinc"], self._names(proxy),
                         "the filter itself did not work")

        proxy.removeFilter(self.ROLE)
        self.assertEqual(
            ["Acrylic", "Aegean", "brass", "zinc"], self._names(proxy),
            "back to All and the list is no longer alphabetical - a "
            "filter change re-filtered without re-sorting")

class CategoriesIsAButtonNotAMenuItem(unittest.TestCase):
    """`Show Categories` left the View menu and became a chip in front of the gear - two controls for one preference is how a toggle ends up disagreeing with the thing it toggles, so the menu row went rather than being mirrored."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))  # the ISOLATED panel - test_grid_scroll records why _protect_live_settings went

    @classmethod
    def tearDownClass(cls):
        pass  # fixture_panel registers stop_panel_workers and deleteLater through class_scope; a worker destroyed by Py_Finalize aborts hython and the push gate reads the exit as not green

    def test_the_button_exists_and_the_menu_row_does_not(self):
        self.assertTrue(hasattr(self.panel, "btn_categories"),
                        "there is no categories button")
        menu = self.panel.ui.findChild(QtWidgets.QMenu, "menuView")
        self.assertIsNotNone(menu, "no View menu to check")
        self.assertNotIn(
            self.panel.action_catview, menu.actions(),
            "Show Categories is still in the View menu as well as on "
            "the toolbar - one preference, two controls")

    def test_the_button_shows_and_hides_the_sidebar(self):
        panel = self.panel
        before = bool(panel.prefs.show_categories)
        self.addCleanup(panel.btn_categories.setChecked, before)

        panel.btn_categories.setChecked(not before)
        QtWidgets.QApplication.processEvents()
        self.assertEqual(
            not before, panel.cat_wrapper.isVisibleTo(panel),
            "the button did not move the sidebar")
        self.assertEqual(
            not before, bool(panel.prefs.show_categories),
            "the preference did not follow the button")

    def test_the_chip_follows_the_action_too(self):
        """The action is still the owner - anything that toggles it must leave the chip agreeing, or the row lies about the state."""
        panel = self.panel
        before = panel.action_catview.isChecked()
        self.addCleanup(panel.action_catview.setChecked, before)
        self.addCleanup(panel.toggle_catview)

        panel.action_catview.setChecked(not before)
        panel.toggle_catview()
        QtWidgets.QApplication.processEvents()
        self.assertEqual(
            panel.action_catview.isChecked(),
            panel.btn_categories.isChecked(),
            "the chip and the action disagree about the sidebar")


class EveryChipUsesTheOneEngine(unittest.TestCase):
    """Every chip goes through the one engine, never patch by patch: two chips had been built by hand from copies of a third and each copy had drifted - one whitened when checked, which no other chip does. The rule the existing chips already followed, now enforced: at rest the art is AS DRAWN, hover lightens, and a chip whose on-state is carried by COLOUR does not lighten at all, because lightening it erases the thing that says it is on."""

    LIT = None

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))  # the ISOLATED panel - test_grid_scroll records why _protect_live_settings went
        cls.LIT = QtGui.QColor(
            ui_helpers.IconMenuButton.LIT_BODY).name()

    @classmethod
    def tearDownClass(cls):
        pass  # fixture_panel registers stop_panel_workers and deleteLater through class_scope; a worker destroyed by Py_Finalize aborts hython and the push gate reads the exit as not green

    def _colours(self, pixmap):
        image = pixmap.toImage()
        return {image.pixelColor(x, y).name()
                for x in range(0, image.width(), 2)
                for y in range(0, image.height(), 2)
                if image.pixelColor(x, y).alpha() > 120}

    def test_no_chip_goes_white_when_it_is_ON(self):
        """No chip is white in any state - none ever was at rest; two copies had invented it."""
        for name in ("btn_categories", "btn_notes", "cb_favsonly",
                     "cb_viewmode"):
            button = getattr(self.panel, name, None)
            if button is None or not getattr(button, "_pms", None):
                continue
            self.assertNotIn(
                self.LIT, self._colours(button._pms[(True, False)]),
                "%s turns white when checked - no chip does that" % name)

    def test_a_colour_signalled_chip_never_lightens(self):
        """Comments, Categories and the favourites star say their state with COLOUR, so hover must leave it alone."""
        for name in ("btn_categories", "btn_notes", "cb_favsonly"):
            button = getattr(self.panel, name, None)
            if button is None or not getattr(button, "_pms", None):
                continue
            for state in ((False, True), (True, True)):
                self.assertNotIn(
                    self.LIT, self._colours(button._pms[state]),
                    "%s lightens in state %s, which erases the colour "
                    "that says whether it is on" % (name, state))

    def test_the_chips_are_BUILT_by_the_shared_engine(self):
        """Not a style point: the drift happened because each chip assembled its own four pixmaps - a new one hand-rolling them again fails here."""
        import inspect
        from amaze.panel import panel as panel_mod
        body = inspect.getsource(panel_mod)
        self.assertNotIn(
            "set_state_pixmaps(", body,
            "a chip is assembling its own states again instead of "
            "calling ChipToggleButton.set_art - that is how two of "
            "them drifted apart in the first place")
        self.assertGreaterEqual(
            body.count(".set_art("), 4,
            "not every chip goes through the shared engine")



class TheOnlineWorld(unittest.TestCase):
    """Online is its own world, parallel to the local sections - not a view mode over the Materials widgets, which is what it used to be. Its tab strip is the SOURCES in source order; the local sections have nothing to do with it (no File tab, and enabled_sections does not apply, because these are not sections), and the amber button is the whole signal that you are in it."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))  # the ISOLATED panel - test_grid_scroll records why _protect_live_settings went

    @classmethod
    def tearDownClass(cls):
        pass  # fixture_panel registers stop_panel_workers and deleteLater through class_scope; a worker destroyed by Py_Finalize aborts hython and the push gate reads the exit as not green

    def setUp(self):
        if self.panel._is_online():
            self.panel.leave_online_world()

    def _tab_keys(self):
        return [key for key, _label in self.panel.section_tabs._segments] \
            if hasattr(self.panel.section_tabs, "_segments") else \
            [k for k, _l in self.panel._online_segments()]

    def test_the_strip_becomes_the_sources(self):
        from amaze.core import matx_sources
        self.panel.enter_online_world()
        self.addCleanup(self.panel.leave_online_world)
        expected = [s.name for s in matx_sources.all_sources()]
        self.assertEqual(
            expected, [k for k, _l in self.panel._online_segments()],
            "the online strip is not the sources in source order")
        self.assertNotIn(
            "file", [k for k, _l in self.panel._online_segments()],
            "File is in the online world - it is a local section and "
            "has no place there")

    def test_a_tab_click_picks_a_SOURCE_not_a_section(self):
        from amaze.core import matx_sources
        names = [s.name for s in matx_sources.all_sources()]
        self.panel.enter_online_world()
        self.addCleanup(self.panel.leave_online_world)
        self.panel._on_tab_toggled(names[1], True)
        QtWidgets.QApplication.processEvents()
        self.assertEqual(
            names[1], self.panel.online_source,
            "clicking an online tab did not change the source")

    def test_leaving_puts_you_back_where_you_came_from(self):
        """The online browser is somewhere you dip into, not a change to what you were working on."""
        panel = self.panel
        panel.section_tabs.setChecked("gradient")
        QtWidgets.QApplication.processEvents()
        came_from = panel.current_section

        panel.enter_online_world()
        QtWidgets.QApplication.processEvents()
        self.assertTrue(panel._is_online(), "did not enter the online world")

        panel.leave_online_world()
        QtWidgets.QApplication.processEvents()
        self.assertFalse(panel._is_online(), "did not leave")
        self.assertEqual(
            came_from, panel.current_section,
            "leaving online dropped you somewhere other than the "
            "section you left from")

    def test_leaving_repoints_the_GRID_not_just_current_section(self):
        """The section you land in is only half of coming back: entering repoints thumblist/cat_list at the online models, so leaving has to repoint them at the local ones - only Material did (exit_online_materials re-activated that one section by name, and the tab bar's setChecked emits nothing when the key has not changed), so the other sections came back with the ONLINE model still in the grid and the next double-click mapped an online proxy index through a local proxy. The sibling test above stayed green throughout, because current_section was never the thing that broke."""
        from amaze.core import matx_sources

        def _no_network(url, *args, **kwargs):
            raise OSError("network blocked in tests")

        real_request = matx_sources._request  # belt and braces: fixture_panel blocks the network too, and a real catalogue worker must never start here whatever the fixture does
        matx_sources._request = _no_network
        self.addCleanup(setattr, matx_sources, "_request", real_request)

        panel = self.panel

        panel.section_tabs.setChecked("gradient")  # GRADIENT, not every section: activating all five against the real library once ran File's folder scan and conversion pass for ten minutes; Colors is the sharpest case anyway - its proxy is a different CLASS, so a grid left on the online model is unmistakable, and the sibling test below pins the call for every section cheaply
        QtWidgets.QApplication.processEvents()

        def _restore_the_panel():  # class-scoped panel: a failure here leaves the grid on the online model and cascades into every later test in this class

            if panel._is_online():
                panel.leave_online_world()
            section = panel._section()
            if section is not None:
                section.activate()
        self.addCleanup(_restore_the_panel)

        local_model = panel.thumblist.model()
        local_sel = panel.thumblist.selectionModel()
        self.assertIsInstance(
            local_model, gradient_library.GradientFilterProxyModel,
            "the Color tab is not on its own proxy, so this test cannot "
            "tell a restored grid from an online one")

        panel.enter_online_world()
        QtWidgets.QApplication.processEvents()
        self.assertIs(
            panel.thumblist.model(), panel.matx_sorted_model,
            "entering the online world did not put the online model in "
            "the grid, so this test proves nothing")

        panel.leave_online_world()
        QtWidgets.QApplication.processEvents()
        self.assertIs(
            panel.thumblist.model(), local_model,
            "left the online world from Color and the grid is still on "
            "the online model")
        self.assertIs(
            panel.thumblist.selectionModel(), local_sel,
            "left the online world from Color and the grid still has "
            "the online SELECTION model - which is what turns a click "
            "into the wrong asset")

    def test_leaving_re_activates_WHICHEVER_section_you_came_from(self):
        """The half the test above cannot afford to check for real: restoring the grid is one call - `_section().activate()` in leave_online_world - and it has to happen whatever tab you left from; activating all five against the real library costs File a filesystem scan and a conversion pass, so this asserts the CALL and the effect is proven once, on Colors, above. Spying on the Section object rather than the panel, because the bug was the panel re-activating one section BY NAME - a spy on the section is blind to that shortcut."""
        from unittest import mock
        from amaze.core import matx_sources

        def _no_network(url, *args, **kwargs):
            raise OSError("network blocked in tests")

        real_request = matx_sources._request
        matx_sources._request = _no_network
        self.addCleanup(setattr, matx_sources, "_request", real_request)

        panel = self.panel
        keys = [k for k, _l in panel.ALL_SECTIONS
                if k in getattr(panel, "sections", {})]
        self.assertTrue(keys, "no local sections to test")

        self.addCleanup(
            lambda: panel.leave_online_world() if panel._is_online() else None)

        for key in keys:
            with self.subTest(section=key):
                section = panel.sections[key]
                panel.current_section = key
                panel._section_before_online = key
                panel.online_mode = True          # pretend we are there
                with mock.patch.object(type(section), "activate") as spy:
                    panel.leave_online_world()
                self.assertTrue(
                    spy.called,
                    "leaving the online world from %r never re-activated "
                    "the section, so the grid keeps the online model"
                    % key)

    def test_the_button_is_the_signal_and_it_is_amber(self):
        from amaze.helpers import theme
        panel = self.panel
        amber = QtGui.QColor(theme.color_hex("star")).name()
        image = panel.btn_online._pms[(True, False)].toImage()
        seen = {image.pixelColor(x, y).name()
                for x in range(0, image.width(), 2)
                for y in range(0, image.height(), 2)
                if image.pixelColor(x, y).alpha() > 120}
        self.assertIn(
            amber, seen,
            "the online button is not amber when on - the colour IS "
            "the signal that you are in the other world")

    def test_a_disabled_chip_is_half_there(self):
        """The star is switched off online, and a chip that paints itself gets no dimming from Qt - so it looked live."""
        self.assertEqual(
            0.5, ui_helpers.ChipToggleButton.DISABLED_OPACITY)
        panel = self.panel
        panel.enter_online_world()
        self.addCleanup(panel.leave_online_world)
        QtWidgets.QApplication.processEvents()
        self.assertFalse(
            panel.cb_favsonly.isEnabled(),
            "the favourites star is still live online, where no record "
            "has a favourite state")
        self.assertFalse(
            panel.btn_notes.isEnabled(),
            "Comments is still live online - a comment is written "
            "against a library asset, which an online result is not")

        panel.leave_online_world()
        QtWidgets.QApplication.processEvents()
        self.assertTrue(panel.cb_favsonly.isEnabled(),
                        "the star did not come back")
        self.assertTrue(panel.btn_notes.isEnabled(),
                        "Comments did not come back")

    def test_the_View_menu_is_down_to_the_one_shot_actions(self):
        """Everything else in it became a button or a tab, and a menu row beside its own button is a second way to one thing - what is left are the ONE-SHOT actions, which are not state and have nothing to duplicate: the two importers and Generate Material; no submenu, three entries do not earn one."""
        menu = self.panel.ui.findChild(QtWidgets.QMenu, "menuView")
        self.assertIsNotNone(menu)
        rows = [a.text() for a in menu.actions() if not a.isSeparator()]
        for gone in ("Material Library", "Show Categories",
                     "Grid View", "List View", "Import Materials"):
            self.assertNotIn(
                gone, rows,
                "%s is still a View menu row - it has a button or a "
                "tab of its own now" % gone)
        self.assertEqual(
            ["Gallery Import (.gal)", "Package Import (.amazepkg)",
             "Generate Material"],
            [r for r in rows if r],
            "the View menu is not the one-shot actions")
        self.assertFalse(
            [a for a in menu.actions() if a.menu() is not None],
            "there is still a submenu in the View menu")


class TheCategoryColumnPaintsITSOwnColour(unittest.TestCase):
    """The one column whose ink is not the shared one: every other cell paints the palette's text colour, so the single colour which MEANS something does not compete with five that do not - Category carries the colour the user gave that category, the same colour the grid puts under those tiles, so the two views agree. The MODEL answers the raw colour (`test_grid_columns` pins that); this is the two things only the VIEW knows - whether the row is selected, and what it is being drawn on."""

    CATEGORY_INK = "#ff8800"  # no other part of the row uses it, and light enough to survive the legibility pass recognisably
    DARK_INK = "#2a2a2a"  # dark enough that writing it on the row would be unreadable - measured 1.03:1 against #333333

    def setUp(self):
        self.view = QtWidgets.QTableView()
        palette = self.view.palette()  # a DARK ROW, like the panel's: on Qt's stock white palette the legibility pass has nothing to do and the test would pass on a premise the panel never has
        palette.setColor(QtGui.QPalette.ColorRole.Base,
                         QtGui.QColor("#313131"))
        self.view.setPalette(palette)
        self.tiles = delegates.AssetItemDelegate(SUBTITLE_ROLE)
        self.delegate = delegates.CategoryCellDelegate(self.tiles)

    def _ink(self, colour, selected=False):  # what the delegate decides the cell's text colour is
        model = QtGui.QStandardItemModel()
        item = QtGui.QStandardItem("Metal")
        if colour is not None:
            item.setData(QtGui.QColor(colour),
                         QtCore.Qt.ItemDataRole.ForegroundRole)
        model.appendRow(item)
        self._model = model                          # keep alive
        option = QtWidgets.QStyleOptionViewItem()
        option.rect = QtCore.QRect(0, 0, ROW_W, ROW_H)
        option.widget = self.view
        option.font = self.view.font()
        option.palette = self.view.palette()
        option.state = QtWidgets.QStyle.StateFlag.State_Enabled
        if selected:
            option.state |= QtWidgets.QStyle.StateFlag.State_Selected
        self.delegate.initStyleOption(option, model.index(0, 0))
        return option.palette.color(QtGui.QPalette.ColorRole.Text)

    @staticmethod
    def _hueish(colour):
        """Which channel dominates - enough to tell an orange category from grey without pinning the legibility pass's exact output, which adjusts lightness and keeps hue."""
        r, g, b = colour.red(), colour.green(), colour.blue()
        return r > g > b and (r - b) > 40

    def test_a_coloured_category_is_not_painted_in_the_shared_ink(self):
        self.assertTrue(
            self._hueish(self._ink(self.CATEGORY_INK)),
            "the Category cell lost the colour the user gave it")

    def test_an_uncoloured_category_uses_the_shared_ink(self):
        plain = self.view.palette().color(QtGui.QPalette.ColorRole.Text)
        self.assertEqual(
            plain.name(), self._ink(None).name(),
            "an uncoloured category asked for an ink of its own")

    def test_a_DARK_category_is_lightened_to_be_readable(self):
        """The pass the grid gets for free and this did not: in grid mode the colour FILLS a band and an ink is picked against it; here the same colour becomes the PEN on the dark row, and #333333 measured 1.03:1."""
        base = self.view.palette().color(QtGui.QPalette.ColorRole.Base)
        painted = self._ink(self.DARK_INK)
        self.assertGreater(
            delegates.AssetItemDelegate.contrast_ratio(painted, base),
            delegates.AssetItemDelegate.contrast_ratio(
                QtGui.QColor(self.DARK_INK), base),
            "a dark category was written on the dark row unchanged")

    def test_a_SELECTED_row_is_LEFT_TO_the_host(self):
        """The delegate adds nothing of its own to a selected row: Houdini's `QAbstractItemView::item:selected` sets the text for every column and the panel inherits that sheet, so the one ink a selected row has is the host's - this used to force the palette here instead, a second opinion about the same pixel. Pinned against a PLAIN delegate rather than a colour: the colour arrives from a stylesheet hython does not load, so what can be checked headless is that this delegate does not diverge from the stock one when the row is selected."""
        ours = self._ink(self.CATEGORY_INK, selected=True)
        stock = self.delegate
        try:
            self.delegate = QtWidgets.QStyledItemDelegate(self.view)
            plain = self._ink(self.CATEGORY_INK, selected=True)
        finally:
            self.delegate = stock
        self.assertEqual(
            plain.name(), ours.name(),
            "the category column overrides a selected row's ink again "
            "- the host owns it")
        self.assertTrue(  # and the UNSELECTED row still gets its colour, or the comparison above passes for a delegate that does nothing at all
            self._hueish(self._ink(self.CATEGORY_INK)),
            "an unselected category lost its own colour")



if __name__ == "__main__":
    unittest.main()
