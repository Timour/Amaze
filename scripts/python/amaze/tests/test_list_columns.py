"""List mode: badges become columns, the slider greys; tests paint rows and read the pixels back."""

import os
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


class ListRowPainting(unittest.TestCase):
    """Render one tile and read it back."""

    def setUp(self):
        self.view = QtWidgets.QListView()  # a grid view: list mode is the table, the delegate has no list branch
        self.delegate = test_support.tile_delegate(
            {"favourite": FAV_ROLE, "open": OPEN_ROLE, "comment": NOTE_ROLE,
             "versions": VERSIONS_ROLE},
            SUBTITLE_ROLE, active_version_role=ACTIVE_ROLE)

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

    def test_the_grid_still_gets_its_badges(self):
        """The badges left list mode only; deleting the badge painters must turn this red."""
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
    """U+2713 is missing from fonts Houdini may fall back to, so the tick is two drawn lines."""

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
    """Grid scales 64-512 with a magnet at 128; a list row does not scale, so the slider greys."""

    def test_the_magnet_pulls_a_near_miss_onto_128(self):
        """A magnet that grabs everything is a broken slider - 200 is a size someone chose."""
        self.assertEqual(
            128, ui_helpers.ClickSlider.DEFAULT_VALUE,
            "the slider's default and its magnet must be the same "
            "number, or the default drags itself off the mark")
        self.assertIn(
            128, ui_helpers.ClickSlider.SNAP_MARKS,
            "128 is the magnet - it has to be in the snap marks")
        slider = ui_helpers.ClickSlider()
        slider.setRange(64, 512)
        for start in (128 - ui_helpers.ClickSlider.SNAP_RADIUS + 1,
                      128 + ui_helpers.ClickSlider.SNAP_RADIUS - 1):
            self.assertEqual(
                128, slider._snap(start),
                "a drag ending %s did not snap to the 128 magnet"
                % start)
        self.assertEqual(200, slider._snap(200),
                         "the magnet swallowed a size someone chose")


class TheRealPanelInListMode(unittest.TestCase):
    """Against the shipped panel: a view built by the test would pass with the panel broken."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))  # the isolated panel, never the live settings

    @classmethod
    def tearDownClass(cls):
        pass  # class_scope stops the workers: one destroyed by Py_Finalize aborts hython

    def _mode(self, mode):
        self.panel.prefs.view_mode = mode
        self.panel.apply_view_mode()
        QtWidgets.QApplication.processEvents()

    HOUSE_FONT = "SideFX Source Sans Pro"

    def _wear_the_host_font(self, table):
        """Wear the host font, PIXEL-sized through `ui_px` ▸p/headless-host-font"""
        if self.HOUSE_FONT not in QtGui.QFontDatabase.families():
            self.skipTest("%s is not installed, so the panel's real font "
                          "cannot be measured here" % self.HOUSE_FONT)
        font = QtGui.QFont(self.HOUSE_FONT)
        font.setPixelSize(theme.ui_px(12))
        table.setFont(font)
        QtWidgets.QApplication.processEvents()

    def test_the_grid_view_never_leaves_icon_mode(self):
        """List mode is the table: the view wearing the tile delegate stays a grid in both modes."""
        self.addCleanup(self._mode, "grid")
        for mode in ("list", "grid", "list"):
            self._mode(mode)
            self.assertEqual(QtWidgets.QListView.ViewMode.IconMode,
                             self.panel.thumblist.viewMode(), mode)

    def test_the_grid_slider_runs_64_to_512(self):
        self.assertEqual(
            (64, 512),
            (self.panel.click_slider.minimum(),
             self.panel.click_slider.maximum()),
            "a grid tile smaller than 64px is not a tile you can read")

    def test_the_slider_is_dead_in_list_mode(self):
        """A list row is one text line with nothing to scale, so the slider is disabled there."""
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
        """Whatever the slider last held in grid, list mode paints its smallest row."""
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
        """Every shown column and its width, read off the real table as Qt measured it."""
        table = self.panel.thumbtable
        return {key: table.columnWidth(column)
                for column, key in enumerate(grid_columns.KEYS)
                if not table.isColumnHidden(column)}

    def _settle(self, width):
        self.panel.resize(width, 600)
        for _ in range(6):
            QtWidgets.QApplication.processEvents()

    def test_narrowing_the_panel_never_drops_a_column(self):
        """A narrower panel, or an open notes pane, never squeezes or drops a column."""
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
        """With no input the geometry holds still: row width does not depend on the viewport."""
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

    def test_no_column_is_narrower_than_what_it_paints(self):
        """Every visible cell fits its column: Qt measures every row in the font it paints with."""
        self._mode("list")
        self.addCleanup(self._mode, "grid")
        self.panel.sync_list_columns()
        QtWidgets.QApplication.processEvents()
        table = self.panel.thumbtable
        self._wear_the_host_font(table)
        proxy = table.model()
        self.assertTrue(proxy.rowCount(), "no rows to measure")
        checked = 0
        for column, key in enumerate(grid_columns.KEYS):
            if table.isColumnHidden(column):
                continue
            width = table.columnWidth(column)  # the whole column: neither the Qt stylesheet examples nor Houdini base.qss pad an item
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
        """A list row fits its 16px thumbnail and one text line, read off the table vertical header."""
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
        """Exactly one of the two views on the model is up; isHidden, as nothing is visible headless."""
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
    """Filters re-sort: setDynamicSortFilter(False) also stops the re-sort after a filter change."""

    ROLE = 257  # 257 is CategoryRole, a shared role number: the list of categories a row is in

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
    """`Show Categories` is a chip, not a View menu row: two controls for one preference drift apart."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))  # the isolated panel, never the live settings

    @classmethod
    def tearDownClass(cls):
        pass  # class_scope stops the workers: one destroyed by Py_Finalize aborts hython

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
        """The action is the owner: whatever toggles it must leave the chip agreeing."""
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
    """One engine for every chip: as drawn at rest, lighter on hover, unless colour shows it is on."""

    LIT = None

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))  # the isolated panel, never the live settings
        cls.LIT = QtGui.QColor(
            ui_helpers.IconMenuButton.LIT_BODY).name()

    @classmethod
    def tearDownClass(cls):
        pass  # class_scope stops the workers: one destroyed by Py_Finalize aborts hython

    def _colours(self, pixmap):
        image = pixmap.toImage()
        return {image.pixelColor(x, y).name()
                for x in range(0, image.width(), 2)
                for y in range(0, image.height(), 2)
                if image.pixelColor(x, y).alpha() > 120}

    def test_no_chip_goes_white_when_it_is_ON(self):
        """No chip is white in any state."""
        hover = ((False, True), (True, True))    # a colour-signalled chip never lightens
        for name, states in (("btn_categories", hover), ("btn_notes", hover),
                             ("cb_favsonly", hover), ("cb_viewmode", ())):
            button = getattr(self.panel, name, None)
            if button is None or not getattr(button, "_pms", None):
                continue
            for state in ((True, False),) + states:
                self.assertNotIn(
                    self.LIT, self._colours(button._pms[state]),
                    "%s turns white in state %s - no chip does that, and "
                    "lightening a colour chip erases the colour that says "
                    "it is on" % (name, state))


class TheOnlineWorld(unittest.TestCase):
    """Online is its own world: its tabs are the sources in order, and the amber button marks it."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))  # the isolated panel, never the live settings

    @classmethod
    def tearDownClass(cls):
        pass  # class_scope stops the workers: one destroyed by Py_Finalize aborts hython

    def setUp(self):
        if self.panel._is_online():
            self.panel.leave_online_world()

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
        """Leaving online repoints the grid and category list of every section at the local models."""
        from amaze.core import matx_sources

        def _no_network(url, *args, **kwargs):
            raise OSError("network blocked in tests")

        real_request = matx_sources._request  # belt and braces: fixture_panel blocks the network too
        matx_sources._request = _no_network
        self.addCleanup(setattr, matx_sources, "_request", real_request)

        panel = self.panel

        panel.section_tabs.setChecked("gradient")  # one section: its proxy is another class, so a grid left online is unmistakable
        QtWidgets.QApplication.processEvents()

        def _restore_the_panel():  # class-scoped panel: a grid left on the online model would fail every later test

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
        """The star is off online, and a chip that paints itself gets no dimming from Qt."""
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
        """The View menu holds only the one-shot actions: the two importers and Generate Material."""
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
    """Category alone paints its own colour, the one the grid puts under its tiles; others share ink."""

    CATEGORY_INK = "#ff8800"  # no other part of the row uses it, and light enough to survive the legibility pass recognisably
    DARK_INK = "#2a2a2a"  # dark enough that writing it on the row would be unreadable - measured 1.03:1 against #333333

    def setUp(self):
        self.view = QtWidgets.QTableView()
        palette = self.view.palette()  # a dark row like the panel: on the stock white palette the legibility pass does nothing
        palette.setColor(QtGui.QPalette.ColorRole.Base,
                         QtGui.QColor("#2d2d2d"))
        self.view.setPalette(palette)
        self.tiles = delegates.AssetItemDelegate(SUBTITLE_ROLE)
        self.delegate = delegates.CategoryCellDelegate(self.tiles)

    def _ink(self, colour, selected=False):  # the text colour the delegate picks for the cell
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
        """Which channel dominates: tells orange from grey without pinning the exact legibility output."""
        r, g, b = colour.red(), colour.green(), colour.blue()
        return r > g > b and (r - b) > 40

    def test_an_uncoloured_category_uses_the_shared_ink(self):
        plain = self.view.palette().color(QtGui.QPalette.ColorRole.Text)
        self.assertEqual(
            plain.name(), self._ink(None).name(),
            "an uncoloured category asked for an ink of its own")

    def test_a_DARK_category_is_lightened_to_be_readable(self):
        """A dark category colour is lightened as the pen on a dark row; #333333 measured 1.03:1."""
        base = self.view.palette().color(QtGui.QPalette.ColorRole.Base)
        painted = self._ink(self.DARK_INK)
        self.assertGreater(
            delegates.AssetItemDelegate.contrast_ratio(painted, base),
            delegates.AssetItemDelegate.contrast_ratio(
                QtGui.QColor(self.DARK_INK), base),
            "a dark category was written on the dark row unchanged")

    def test_a_SELECTED_row_is_LEFT_TO_the_host(self):
        """A selected row is left to the host stylesheet: the delegate paints it like a plain one."""
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
        self.assertTrue(  # the unselected row still gets its colour, or a do-nothing delegate passes
            self._hueish(self._ink(self.CATEGORY_INK)),
            "an unselected category lost its own colour")


if __name__ == "__main__":
    unittest.main()
