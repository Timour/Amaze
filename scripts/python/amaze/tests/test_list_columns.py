"""List mode: badges become COLUMNS, and the slider stops pretending.

The 2026-08-01 decision, in two halves.

A list row is one text line tall with a 16px thumbnail, and the four
corner badges were being drawn on it anyway - a 12px mark on a 16px
picture, covering most of what it annotated. So in list mode the badges
are not drawn at all, and the four facts they carry (Favorite, Version,
Open, Notes) become columns. The Version column is the one that gains
from the move: a badge could only say "this asset has versions", while
a column has room to say WHICH version you are looking at.

The marks are ticks rather than the words true/false - a column of the
word "false" is a wall of text that says nothing.

And the slider: grid runs 64-512 with a magnet at 128, while list is
fixed at its smallest size. A list row does not scale, so the slider is
greyed out there instead of moving a number nothing reads.

These tests PAINT. An earlier badge test asserted that a method body
mentioned a variable and stayed green through a sabotage that deleted
the code using it (practice.md, 2026-07-29), so nothing here trusts a
constant or a flag: a row is rendered and the pixels are read back.
"""

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
        # A GRID view. This class rendered LIST rows until 2026-08-04;
        # the one test left in it is the grid half, and the delegate
        # has no list branch left to put it in.
        self.view = QtWidgets.QListView()
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
        """Non-background pixels in a column band, as a set of RGB.

        The column RULES are not ink: every column edge draws a divider
        line, so an empty column still has two grey verticals in its
        band. They are furniture, not content."""
        # The painted strip's own divider grey. It drew a rule at
        # every column edge, so an empty column still had two greys in
        # its band - furniture, not content. Kept as a literal now the
        # strip is gone; this reader is only used by the grid test
        # below, which paints no rules at all.
        rule = (0x45, 0x45, 0x45)
        found = set()
        for x in range(max(0, x0), min(image.width(), x1)):
            for y in range(image.height()):
                rgb = image.pixelColor(x, y)
                value = (rgb.red(), rgb.green(), rgb.blue())
                if value != rule and sum(value) > 40:
                    found.add(value)
        return found

    def _col_x(self, which):
        """Left edge of a mark column, in the order the row paints
        them: ... | Favorite | Version | Open | Notes."""
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
        """The badges did not go away - they went out of LIST mode.
        Without this, deleting the badge painters entirely would leave
        every test above green."""
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
    """U+2713 is missing from fonts Houdini may fall back to, and a
    missing glyph is an empty box in a column whose whole job is to be
    a yes. The tick is two drawn lines instead."""

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
    """Grid scales 64-512 with a magnet at 128; a list row is one text
    line and does not scale, so the slider is greyed there."""

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
        """A magnet that grabs everything is a broken slider - 200 is
        a size someone chose."""
        slider = ui_helpers.ClickSlider()
        slider.setRange(64, 512)
        self.assertEqual(200, slider._snap(200))


class TheRealPanelInListMode(unittest.TestCase):
    """Against the SHIPPED panel: a view built by the test would pass
    with the panel broken (the lesson test_grid_scroll records)."""

    @classmethod
    def setUpClass(cls):
        # The ISOLATED panel - see test_grid_scroll for why this
        # stopped using _protect_live_settings on 2026-08-02.
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    @classmethod
    def tearDownClass(cls):
        # Stop the panel's QThreads FIRST. The online catalogue and
        # preview workers shut down on the app's aboutToQuit, which
        # hython never emits - so a worker left running is destroyed
        # by Py_Finalize and Qt aborts the process. The suite passed
        # and the runner still exited 134, which the push gate reads
        # as "not green" and refuses.
        # fixture_panel registers stop_panel_workers and deleteLater
        # through class_scope, so both already run after the last test.
        pass

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
        """A list row is one text line - there is nothing to scale, so
        the control says so instead of moving a number nothing reads."""
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
        """Whatever the slider last held in grid, list paints its
        smallest row - "list mode should only display at the smallest
        scale"."""
        self._mode("grid")
        self.panel.click_slider.setValue(512)
        QtWidgets.QApplication.processEvents()
        self._mode("list")
        self.addCleanup(self._mode, "grid")
        self.assertEqual(
            self.panel.LIST_THUMB_SIZE, self.panel._active_thumbsize(),
            "list mode followed the grid slider instead of staying at "
            "its own smallest size")

    def _columns(self):
        """Every SHOWN column and its width, off the real table.

        It used to read ten `_list_*_w` attributes the panel pushed
        into the delegate. There is no push any more - a column is as
        wide as Qt measures its contents - so this asks the widget that
        knows.
        """
        table = self.panel.thumbtable
        return {key: table.columnWidth(column)
                for column, key in enumerate(grid_columns.KEYS)
                if not table.isColumnHidden(column)}

    def _settle(self, width):
        self.panel.resize(width, 600)
        for _ in range(6):
            QtWidgets.QApplication.processEvents()

    def test_narrowing_the_panel_never_drops_a_column(self):
        """The report: "rows collapse randomly when you make the
        notewindow bigger". A row used to be defined as the width of
        the panel, so anything that took panel width - the notes pane
        most of all - made the fitting code squeeze columns and then
        delete them from the right. Nothing about a name or a tag list
        gets shorter because a pane moved."""
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
        """The fear that kept the horizontal scrollbar off for so long,
        turned into a test. The loop needs the row width to depend on
        the viewport; it does not any more, so the geometry must hold
        still with no input."""
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
        """The truncation complaint, pinned: a Version column too
        narrow for an ordinary version name elides it to "Versio...".

        It had two causes, and the table removes both by construction.
        The columns were MEASURED with the view's font and PAINTED with
        the delegate's, so every one was fitted just under its own
        content; and the fit sampled rows, so a column could be too
        narrow for a value the sample missed. Qt measures what it
        draws, with the font it draws it in. This asserts the PROPERTY
        rather than the old floors: every visible cell fits.
        """
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
            # THE WHOLE COLUMN. There is no cell padding to subtract:
            # neither Qt's stylesheet examples nor Houdini's own
            # base.qss pads an item, and the table wears Houdini's
            # metrics now. Qt measures what it draws, so the column IS
            # the room the text has.
            width = table.columnWidth(column)
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
        """The complaint that started this: "30px tall for a text line
        is not small, its a list". The row now fits its 16px thumbnail
        and its text, and nothing else - the flat 14px of padding that
        made it 30 is gone."""
        self._mode("list")
        self.addCleanup(self._mode, "grid")
        _w, height = self.panel._list_grid_size(self.panel.LIST_THUMB_SIZE)
        fm = QtGui.QFontMetrics(self.panel.thumblist.font())
        self.assertLessEqual(
            height, max(fm.height(), self.panel.LIST_THUMB_SIZE)
            + theme.ui_px(8),
            "a list row is taller than the things inside it need - "
            "it got %spx for a %spx thumbnail and a %spx text line"
            % (height, self.panel.LIST_THUMB_SIZE, fm.height()))
        self.assertGreaterEqual(
            height, self.panel.LIST_THUMB_SIZE,
            "the row is shorter than its own thumbnail")


if __name__ == "__main__":
    unittest.main()


class FilteringNeverUnsortsTheList(unittest.TestCase):
    """Pick a category, go back to All, and the list was no longer
    alphabetical - "things starting with A do not end up first".

    The proxy runs with setDynamicSortFilter(False) for performance,
    and that switch turns off BOTH halves: no automatic re-sort after
    a filter change either, so rows returning to view came back in
    source order. One call site knew (the renderer filter called
    sort(0) itself); category, search and favourites did not.

    Tested at the PROXY, because that is where the guarantee now
    lives - a panel test would prove it for one section and leave the
    other four to be found by hand.
    """

    #: The proxy matches on the role NUMBERS the sections share -
    #: 257 is CategoryRole, and it expects the list of categories a
    #: material belongs to.
    ROLE = 257

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

    # A second test asked whether the rows INSIDE a category are
    # sorted, and it was deleted: it passed with the fix removed. The
    # proxy filters its already-sorted mapping, so a filtered view
    # stays in order whether or not anything re-sorts - the test could
    # not fail, and a test that cannot fail is not a guard.


class CategoriesIsAButtonNotAMenuItem(unittest.TestCase):
    """"Show Categories" left the View menu and became a chip in front
    of the gear (2026-08-01). Two controls for one preference is how a
    toggle ends up disagreeing with the thing it toggles, so the menu
    row went rather than being mirrored."""

    @classmethod
    def setUpClass(cls):
        # The ISOLATED panel - see test_grid_scroll for why this
        # stopped using _protect_live_settings on 2026-08-02.
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    @classmethod
    def tearDownClass(cls):
        # Stop the panel's QThreads FIRST. The online catalogue and
        # preview workers shut down on the app's aboutToQuit, which
        # hython never emits - so a worker left running is destroyed
        # by Py_Finalize and Qt aborts the process. The suite passed
        # and the runner still exited 134, which the push gate reads
        # as "not green" and refuses.
        # fixture_panel registers stop_panel_workers and deleteLater
        # through class_scope, so both already run after the last test.
        pass

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
        """The action is still the owner - anything that toggles it
        must leave the chip agreeing, or the row lies about the
        state."""
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
    """
    logic and same engine. not a patch by patch". Two chips had been
    built by hand from copies of a third, and each copy had drifted -
    one of them whitened when checked, which no other chip does.

    The rule the existing chips already followed, now enforced: at
    rest the art is AS DRAWN, hover lightens, and a chip whose
    on-state is carried by COLOUR does not lighten at all, because
    lightening it erases the thing that says it is on.
    """

    LIT = None

    @classmethod
    def setUpClass(cls):
        # The ISOLATED panel - see test_grid_scroll for why this
        # stopped using _protect_live_settings on 2026-08-02.
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))
        cls.LIT = QtGui.QColor(
            ui_helpers.IconMenuButton.LIT_BODY).name()

    @classmethod
    def tearDownClass(cls):
        # Stop the panel's QThreads FIRST. The online catalogue and
        # preview workers shut down on the app's aboutToQuit, which
        # hython never emits - so a worker left running is destroyed
        # by Py_Finalize and Qt aborts the process. The suite passed
        # and the runner still exited 134, which the push gate reads
        # as "not green" and refuses.
        # fixture_panel registers stop_panel_workers and deleteLater
        # through class_scope, so both already run after the last test.
        pass

    def _colours(self, pixmap):
        image = pixmap.toImage()
        return {image.pixelColor(x, y).name()
                for x in range(0, image.width(), 2)
                for y in range(0, image.height(), 2)
                if image.pixelColor(x, y).alpha() > 120}

    def test_no_chip_goes_white_when_it_is_ON(self):
        """"i dont want it white in any state" - and no chip ever did
        at rest; two copies had invented it."""
        for name in ("btn_categories", "btn_notes", "cb_favsonly",
                     "cb_viewmode"):
            button = getattr(self.panel, name, None)
            if button is None or not getattr(button, "_pms", None):
                continue
            self.assertNotIn(
                self.LIT, self._colours(button._pms[(True, False)]),
                "%s turns white when checked - no chip does that" % name)

    def test_a_colour_signalled_chip_never_lightens(self):
        """Comments, Categories and the favourites star say their
        state with COLOUR, so hover must leave it alone."""
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
        """Not a style point: the drift happened because each chip
        assembled its own four pixmaps. If a new one hand-rolls them
        again, this fails."""
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
    """Online is its own world, parallel to the local sections - not a
    view mode over the Materials widgets, which is what it used to be.

    Its tab strip is the SOURCES, in source order, and the local
    sections have nothing to do with it: no File tab, and the
    enabled_sections preference does not apply, because these are not
    sections. The amber button is the whole signal that you are in it.
    """

    @classmethod
    def setUpClass(cls):
        # The ISOLATED panel - see test_grid_scroll for why this
        # stopped using _protect_live_settings on 2026-08-02.
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    @classmethod
    def tearDownClass(cls):
        # Stop the panel's QThreads FIRST. The online catalogue and
        # preview workers shut down on the app's aboutToQuit, which
        # hython never emits - so a worker left running is destroyed
        # by Py_Finalize and Qt aborts the process. The suite passed
        # and the runner still exited 134, which the push gate reads
        # as "not green" and refuses.
        # fixture_panel registers stop_panel_workers and deleteLater
        # through class_scope, so both already run after the last test.
        pass

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
        """
        a change to what you were working on."""
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
        """The section you land in is only half of coming back.

        Entering repoints thumblist/cat_list at the online models, so
        leaving has to repoint them at the local ones. Until 2026-08-02
        only Material did: exit_online_materials re-activated that one
        section by name, and the tab bar's setChecked emits nothing
        when the key has not changed - so Node, Code, Color and File
        came back with the ONLINE model still in the grid, and the next
        double-click mapped an online proxy index through a local
        proxy. The sibling test above stayed green throughout, because
        current_section was never the thing that broke.
        """
        # This class builds its panel through _protect_live_settings,
        # which does NOT block the network the way fixture_panel does -
        # so entering the online world here starts a real catalogue
        # worker per entry.
        from amaze.core import matx_sources

        def _no_network(url, *args, **kwargs):
            raise OSError("network blocked in tests")

        real_request = matx_sources._request
        matx_sources._request = _no_network
        self.addCleanup(setattr, matx_sources, "_request", real_request)

        panel = self.panel

        # GRADIENT, not every section, and not File. The first version
        # of this test walked all five, which meant a real activate()
        # per section against the REAL library - and the File section's
        # activate scans the user's registered folders and converts
        # every image it finds. It did not fail; it ran for over ten
        # minutes and read like a hung suite. Colors is the sharpest
        # single case anyway: it is the one section whose proxy is a
        # different CLASS (GradientFilterProxyModel), so a grid left on
        # the online model is unmistakable rather than a same-typed
        # object that happens to be the wrong instance. The mechanism
        # is per-section-agnostic - one _section().activate() call in
        # leave_online_world - and the sibling test below pins that it
        # is reached for every section, cheaply.
        panel.section_tabs.setChecked("gradient")
        QtWidgets.QApplication.processEvents()

        # The panel is class-scoped, and a failure here leaves the grid
        # on the online model - which would cascade into every later
        # test in this class rather than failing alone.
        def _restore_the_panel():
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
        """The half the test above cannot afford to check for real.

        Restoring the grid is one call - `_section().activate()` in
        leave_online_world - and it has to happen whatever tab you left
        from. Actually activating all five against the real library
        costs a filesystem scan and an image conversion pass for the
        File section, so this asserts the CALL instead of its effect:
        the effect is proven once, on Colors, above.

        Spying on the Section object rather than the panel, because the
        bug was that the panel re-activated one section BY NAME - a
        spy on the section is blind to that shortcut and would only see
        the honest route.
        """
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
        """The star is switched off online, and a chip that paints
        itself gets no dimming from Qt - so it looked live."""
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

    def test_the_View_menu_is_down_to_the_two_importers(self):
        """Everything else in it became a button or a tab, and a menu
        row beside its own button is a second way to one thing - which
        is how a toggle ends up disagreeing with what it toggles.

        What is left are the two ONE-SHOT actions, which are not state
        and so have nothing to duplicate: Gallery Import and Generate
        Material. No submenu either - two entries do not earn one."""
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
            ["Gallery Import (.gal)", "Generate Material"],
            [r for r in rows if r],
            "the View menu is not the two importers")
        self.assertFalse(
            [a for a in menu.actions() if a.menu() is not None],
            "there is still a submenu in the View menu")


class TheCategoryColumnPaintsITSOwnColour(unittest.TestCase):
    """The one column whose ink is not the shared one.

    Every other cell paints the palette's text colour - one colour, so
    that the single colour which MEANS something does not compete with
    five that do not. Category carries the colour the user gave that
    category, and it is the same colour the grid puts under those
    tiles, so the two views agree about what a category looks like.

    The MODEL answers the raw colour (`test_grid_columns` pins that);
    this is the two things only the VIEW knows - whether the row is
    selected, and what it is being drawn on.
    """

    #: A colour no other part of the row uses, light enough to survive
    #: the legibility pass without being changed beyond recognition.
    CATEGORY_INK = "#ff8800"
    #: Dark enough that writing it on the row would be unreadable -
    #: measured 1.03:1 against #333333.
    DARK_INK = "#2a2a2a"

    def setUp(self):
        self.view = QtWidgets.QTableView()
        # A DARK ROW, like the panel's. The legibility pass is against
        # the palette's actual base, so on Qt's stock white palette
        # there is nothing for it to do and the test would pass on a
        # premise the panel never has.
        palette = self.view.palette()
        palette.setColor(QtGui.QPalette.ColorRole.Base,
                         QtGui.QColor("#313131"))
        self.view.setPalette(palette)
        self.tiles = delegates.AssetItemDelegate(SUBTITLE_ROLE)
        self.delegate = delegates.CategoryCellDelegate(self.tiles)

    def _ink(self, colour, selected=False):
        """What the delegate decides the cell's text colour is."""
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
        """Which channel dominates - enough to tell an orange category
        from grey without pinning the legibility pass's exact output,
        which adjusts lightness and keeps hue."""
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
        """The pass the grid gets for free and this did not: in grid
        mode the colour FILLS a band and an ink is picked against it;
        here the same colour becomes the PEN on the dark row, and
        #333333 measured 1.03:1."""
        base = self.view.palette().color(QtGui.QPalette.ColorRole.Base)
        painted = self._ink(self.DARK_INK)
        self.assertGreater(
            delegates.AssetItemDelegate.contrast_ratio(painted, base),
            delegates.AssetItemDelegate.contrast_ratio(
                QtGui.QColor(self.DARK_INK), base),
            "a dark category was written on the dark row unchanged")

    def test_a_SELECTED_row_is_LEFT_TO_the_host(self):
        """The delegate adds nothing of its own to a selected row.

        Houdini's `QAbstractItemView::item:selected` sets the text to
        `TextColor` for every column, and the panel already inherits
        that sheet - so the one ink a selected row has is the host's.
        This used to force the palette here instead, which is a second
        opinion about the same pixel.

        Pinned against a PLAIN delegate rather than against a colour:
        the colour arrives from a stylesheet hython does not load, so
        asserting one here would be asserting the harness. What can be
        checked headless is that this delegate does not diverge from
        the stock one when the row is selected."""
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
        # And the UNSELECTED row still gets the category's colour, or
        # the comparison above would pass for a delegate that does
        # nothing at all.
        self.assertTrue(
            self._hueish(self._ink(self.CATEGORY_INK)),
            "an unselected category lost its own colour")

