"""The Grid's COLUMNS as a MODEL fact - step 1 of the table migration.

List mode has been a table COSTUME since it was built: a `QListView`
in ListMode whose delegate paints ten regions inside one item's rect,
under a hand-painted header strip. 681 lines, no click-sorting, no
drag-resizing. Decided 2026-08-04, once the cost of changing it
after release: *"changing it after release costs far more."*

THIS STEP IS ADDITIVE AND CANNOT BE SEEN. Column 0 answers exactly
what the model answered before, for every role; columns 1..9 are new.
`QListView` shows `modelColumn()` 0 and nothing else, so **grid mode
is untouched by construction** - which is the property that makes the
migration safe to land in pieces rather than one commit.

The measured fact that shaped it: a `QAbstractListModel`'s
`index(row, col)` returns an INVALID index for any col > 0 even when
`columnCount` says ten. A list model is not a table with its columns
switched off; it is a different model. So the four grid models are
`QAbstractTableModel` now.

The MECHANISM behind that was re-probed 2026-08-05 and the first
answer was wrong: nothing hard-codes column 0, and `columnCount` is
callable and returns the override. `hasIndex()` is what refuses -
`QAbstractListModel` declares `columnCount` private in C++, so PySide6
never installs the Python override into the vtable, and `hasIndex()`
calls it VIRTUALLY and gets Qt's own 1 while Python calling the same
method gets ten. The two disagree and nothing shows it from Python.
The conclusion was right anyway, which is how the wrong reason
survived. Full probe in research.md ▸ Qt widgets, views & painting.
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import grid_columns  # noqa: E402
from amaze.panel import delegates  # noqa: E402
from amaze.helpers import theme, ui_helpers  # noqa: E402
from amaze.tests import test_support  # noqa: E402

PACKAGE = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))

#: (section key, panel attribute) for every model the Grid shows.
GRID_MODELS = (
    ("material", "material_model"),
    ("cop", "cop_model"),
    ("code", "code_model"),
    ("file", "file_files_model"),
    ("gradient", "gradient_model"),
)


class ThereIsONEColumnOrder(unittest.TestCase):

    def test_every_model_reads_the_SAME_list(self):
        """The order was defined on the painted header WIDGET, and the
        models cannot import that (`ui_helpers` imports `core.debug`,
        so it would cycle) - which is why it moved to `core`. The
        widget is gone; the reason it moved is not."""
        for name in ("material_model", "gradient_model", "node_model"):
            model = getattr(self.panel, name, None)
            if model is None:
                continue
            with self.subTest(model=name):
                self.assertEqual(
                    len(grid_columns.COLUMNS), model.columnCount(),
                    "%s counts a different number of columns" % name)
                for column, (_key, label) in enumerate(grid_columns.COLUMNS):
                    self.assertEqual(
                        label or None,
                        model.headerData(
                            column, QtCore.Qt.Orientation.Horizontal,
                            QtCore.Qt.ItemDataRole.DisplayRole) or None,
                        "%s labels column %d differently" % (name, column))

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))


class AGridModelAnswersPerCOLUMN(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _models(self):
        for key, attr in GRID_MODELS:
            model = getattr(self.panel, attr, None)
            if model is not None and model.rowCount():
                yield key, model

    def test_every_grid_model_is_a_TABLE_model(self):
        """A list model refuses column > 0 whatever columnCount says -
        measured, and the reason this is not a mixin over the old base."""
        for key, model in self._models():
            with self.subTest(section=key):
                self.assertIsInstance(model, QtCore.QAbstractTableModel)
                self.assertIsInstance(model, grid_columns.GridColumnsMixin)

    def test_every_grid_model_offers_the_same_column_count(self):
        """The header is shared, so a model with its own idea of how
        many columns there are would label somebody else's."""
        for key, model in self._models():
            with self.subTest(section=key):
                self.assertEqual(len(grid_columns.COLUMNS),
                                 model.columnCount())

    def test_an_index_in_a_LATER_column_is_valid(self):
        """The whole point, and the thing the old base made impossible."""
        for key, model in self._models():
            with self.subTest(section=key):
                index = model.index(0, 3)
                self.assertTrue(index.isValid(),
                                "%s cannot address column 3" % key)
                self.assertEqual(3, index.column())

    def test_COLUMN_ZERO_answers_exactly_what_it_used_to(self):
        """The safety property. Grid mode reads column 0 and nothing
        else, so if this drifts the whole migration is visible."""
        display = QtCore.Qt.ItemDataRole.DisplayRole
        for key, model in self._models():
            with self.subTest(section=key):
                # A NAMED row, found rather than assumed: the material
                # fixture's row 0 carries an empty name on purpose, and
                # the first version of this test read that as the
                # column having broken.
                named = [row for row in range(min(model.rowCount(), 40))
                         if model.index(row, 0).data(display)]
                self.assertTrue(named, "%s has no named row to check" % key)
                index = model.index(named[0], 0)
                self.assertTrue(index.data(display))
                # A UserRole the grid delegate reads must still answer
                # here - column 0 is where every existing reader looks.
                role = getattr(model, "FavoriteRole", None)
                if role is not None:
                    self.assertIsNot(
                        index.data(role), NotImplemented,
                        "%s stopped answering a UserRole on column 0"
                        % key)

    def test_the_NAME_column_repeats_the_display_name(self):
        for key, model in self._models():
            with self.subTest(section=key):
                column = grid_columns.KEYS.index("name")
                self.assertEqual(
                    model.index(0, 0).data(
                        QtCore.Qt.ItemDataRole.DisplayRole),
                    model.index(0, column).data(
                        QtCore.Qt.ItemDataRole.DisplayRole),
                    "%s's Name column does not show the row's name" % key)

    def test_a_column_the_model_cannot_fill_answers_NOTHING(self):
        """Color has no Tags and File has no Version. Neither knows the
        other exists - the column is simply absent from its map."""
        gradient = self.panel.gradient_model
        tags = grid_columns.KEYS.index("tags")
        self.assertIsNone(
            gradient.index(0, tags).data(
                QtCore.Qt.ItemDataRole.DisplayRole),
            "Color answered the Tags column, which it has no data for")
        files = self.panel.file_files_model
        version = grid_columns.KEYS.index("version")
        self.assertIsNone(
            files.index(0, version).data(
                QtCore.Qt.ItemDataRole.DisplayRole)
            if files.rowCount() else None,
            "File answered the Version column")

    def test_a_LIST_of_values_is_joined_for_display(self):
        """Categories and tags are lists on the record. A cell shows
        text, and `['Metal', 'Wood']` is not it."""
        model = self.panel.material_model
        if not model.rowCount():
            self.skipTest("no materials in the fixture")
        column = grid_columns.KEYS.index("category")
        for row in range(min(model.rowCount(), 25)):
            value = model.index(row, column).data(
                QtCore.Qt.ItemDataRole.DisplayRole)
            self.assertNotIsInstance(
                value, (list, tuple),
                "the Category column handed a %s straight to the view"
                % type(value).__name__)

    def test_a_non_display_role_stays_column_ZEROs_business(self):
        """Decoration and the rest are read by the grid delegate off
        column 0. Answering them in every column would put the
        thumbnail in all ten."""
        model = self.panel.material_model
        if not model.rowCount():
            self.skipTest("no materials in the fixture")
        column = grid_columns.KEYS.index("type")
        self.assertIsNone(
            model.index(0, column).data(
                QtCore.Qt.ItemDataRole.DecorationRole),
            "a later column answered DecorationRole")

    def test_the_header_labels_come_from_the_model(self):
        for key, model in self._models():
            with self.subTest(section=key):
                for column, (_k, label) in enumerate(grid_columns.COLUMNS):
                    self.assertEqual(
                        label or None,
                        model.headerData(
                            column, QtCore.Qt.Orientation.Horizontal,
                            QtCore.Qt.ItemDataRole.DisplayRole) or None)


class ACellSAYSWhatItIs(unittest.TestCase):
    """How a cell READS. Four decisions taken on the first shipped
    table (2026-08-04): the name is bold, the category is written in
    the colour that category was given, every cell has air either
    side, and a tick column measures its mark.

    All of them are answered by the MODEL or by Qt's own knobs, not by
    a painter: a font role, a foreground role, a style metric.
    Nothing here draws anything.
    """

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _column(self, key):
        return grid_columns.KEYS.index(key)

    def test_NO_column_asks_for_a_font_of_its_own(self):
        """The rows wear the VIEW's font, like every other list in the
        host.

        A bold Name column was asked for and then taken back out on
        2026-08-04. The reason it had to go is worth keeping: Qt uses
        `FontRole` AS-IS, so answering it with a bare `QFont()` with
        bold set hands the cell Qt's DEFAULT family and size - not the
        panel's font in bold, a different typeface. Same shape as the
        absolute point-size floor that made Windows rows disagree.

        If a weight is ever wanted again it has to be derived from the
        view's font, not constructed beside it."""
        model = self.panel.material_model
        if not model.rowCount():
            self.skipTest("no materials in the fixture")
        for key in ("name", "type", "category", "tags"):
            with self.subTest(column=key):
                self.assertIsNone(
                    model.index(0, self._column(key)).data(
                        QtCore.Qt.ItemDataRole.FontRole),
                    "%s asked for a font of its own - a role-supplied "
                    "font replaces the view's family and size, it does "
                    "not add weight to them" % key)

    def test_the_CATEGORY_is_written_in_the_CATEGORYS_OWN_COLOUR(self):
        """The colour the user gave that category, and the same one the
        grid paints under its tiles - so the two views cannot disagree
        about what a category looks like."""
        panel = self.panel
        model = panel.material_model
        column = self._column("category")
        role = getattr(model, "CategoryColorRole", None)
        self.assertIsNotNone(
            role, "the model carries no per-row category colour")
        row = self._colour_a_category("#ff8800")
        colour = model.index(row, 0).data(role)
        self.assertTrue(
            colour, "colouring the category did not reach the asset row")
        ink = model.index(row, column).data(
            QtCore.Qt.ItemDataRole.ForegroundRole)
        self.assertIsNotNone(ink, "the Category cell asked for no colour")
        self.assertEqual(
            QtGui.QColor(colour).name(), ink.name(),
            "the Category cell is not the category's own colour")

    def _colour_a_category(self, colour):
        """Give one category a colour and return the row wearing it.

        COLOUR ONE, do not go looking for one: the fixture ships none
        coloured, so both of these tests read green against a library
        where there was nothing to colour anything with. One skipped
        itself; the other stayed green with `name` deliberately wired
        to the category ink. "A harder SETUP, never a weaker
        assertion" - practice.md.
        """
        model = self.panel.material_model
        column = self._column("category")
        row = next((r for r in range(model.rowCount())
                    if model.index(r, column).data(
                        QtCore.Qt.ItemDataRole.DisplayRole)), None)
        self.assertIsNotNone(row, "no fixture asset has a category")
        name = model.index(row, column).data(
            QtCore.Qt.ItemDataRole.DisplayRole)
        categories = self.panel.category_model
        self.addCleanup(categories.set_color, name,
                        categories.color_of(name))
        categories.set_color(name, colour)
        return row

    def test_only_the_CATEGORY_column_colours_itself(self):
        model = self.panel.material_model
        row = self._colour_a_category("#ff8800")
        for key in ("name", "type", "tags", "license"):
            with self.subTest(column=key):
                self.assertIsNone(
                    model.index(row, self._column(key)).data(
                        QtCore.Qt.ItemDataRole.ForegroundRole),
                    "%s coloured itself - only Category does" % key)

    def test_a_row_whose_category_has_NO_colour_asks_for_none(self):
        """No colour is not black. Answering `ForegroundRole` with an
        invalid QColor paints the text in whatever that is."""
        model = self.panel.material_model
        column = self._column("category")
        role = model.CategoryColorRole
        for row in range(model.rowCount()):
            if model.index(row, 0).data(role):
                continue
            self.assertIsNone(
                model.index(row, column).data(
                    QtCore.Qt.ItemDataRole.ForegroundRole),
                "an uncoloured category still asked for an ink")
            return
        self.skipTest("every fixture category has a colour")

    def test_NO_column_overrides_its_alignment(self):
        """Including the tick columns. They were centred for one build
        and reverted (2026-08-04): a `QHeaderView` label starts at the
        cell's left edge, so a centred mark reads as a different table
        from the eight columns beside it."""
        model = self.panel.material_model
        for key in (("name", "type", "category", "tags")
                    + grid_columns.GridColumnsMixin.TICK_COLUMNS):
            with self.subTest(column=key):
                self.assertIsNone(
                    model.index(0, self._column(key)).data(
                        QtCore.Qt.ItemDataRole.TextAlignmentRole),
                    "%s overrode an alignment it has no opinion about"
                    % key)

    def _every_model(self):
        panel = self.panel
        for key in ("material_model", "gradient_model", "node_model"):
            model = getattr(panel, key, None)
            if model is not None and model.rowCount():
                yield key, model


class ATickColumnIsAsWideAsTheTICK(unittest.TestCase):
    """"the favourite and comment columns sized wrong" (2026-08-04).

    They did not: `ResizeToContents` measures `DisplayRole`, that role
    still carries the raw yes/no because the SORT compares it, and so
    the column asked for room to print the word "False" - which is
    never drawn.
    """

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def test_the_hint_ignores_the_value_behind_the_mark(self):
        panel = self.panel
        column = grid_columns.KEYS.index("favorite")
        table = panel.thumbtable
        delegate = table.itemDelegateForColumn(column)
        self.assertIsInstance(delegate, delegates.TickCellDelegate)
        option = QtWidgets.QStyleOptionViewItem()
        option.font = table.font()
        option.fontMetrics = QtGui.QFontMetrics(table.font())
        index = table.model().index(0, column)
        plain = QtWidgets.QStyledItemDelegate(table)
        self.assertEqual(
            delegates.TickCellDelegate.SIDE
            + 2 * delegates.TickCellDelegate.PAD,
            delegate.sizeHint(option, index).width(),
            "a tick column does not ask for the tick's own width")
        self.assertLessEqual(
            delegate.sizeHint(option, index).width(),
            plain.sizeHint(option, index).width(),
            "the tick asks for MORE room than printing the value would")

    def test_the_mark_starts_where_every_other_column_does(self):
        table = self.panel.thumbtable
        column = grid_columns.KEYS.index("favorite")
        delegate = table.itemDelegateForColumn(column)
        cell = QtCore.QRect(40, 0, 120, 20)
        box = delegate._box(cell)
        self.assertEqual(
            cell.left() + delegate.PAD, box.left(),
            "the tick does not sit at the cell's left edge")
        self.assertEqual(
            self.panel.CELL_PAD, delegate.PAD,
            "the tick's inset is not the padding every other cell has")

    def test_a_tick_cell_PAINTS_ITSELF_when_the_row_is_selected(self):
        """The first live build broke here: the highlight band stopped
        dead at Favorite and started again after it, because this
        delegate drew the mark and never drew the CELL. Two gaps in
        the band, and the gaps were exactly the tick columns.

        Compared against what a PLAIN cell paints under the same
        option, in the strip to the right of the mark. The first
        version sampled one corner pixel and asserted it equalled the
        palette's Highlight - which is a claim about how a STYLE draws
        a selection, not about this delegate. H21's style leaves that
        corner alone, so it read black and the test failed on a
        machine where the code was correct.
        """
        table = self.panel.thumbtable
        column = grid_columns.KEYS.index("favorite")
        delegate = table.itemDelegateForColumn(column)
        index = table.model().index(0, column)
        # A plain cell with NO TEXT, which is what a tick cell is: the
        # background and nothing else. The first comparison used the
        # REAL index, so it put our mark against the printed word
        # "True" - a difference for the right reason, in a test that
        # is about the background.
        blank_model = QtGui.QStandardItemModel()
        blank_model.appendRow(QtGui.QStandardItem(""))
        self.addCleanup(blank_model.deleteLater)
        plain = QtWidgets.QStyledItemDelegate(table)

        def render(with_delegate, on_index):
            option = QtWidgets.QStyleOptionViewItem()
            option.rect = QtCore.QRect(0, 0, 60, 20)
            option.state = (QtWidgets.QStyle.StateFlag.State_Enabled
                            | QtWidgets.QStyle.StateFlag.State_Selected
                            | QtWidgets.QStyle.StateFlag.State_Active)
            option.palette = table.palette()
            option.font = table.font()
            option.widget = table
            image = QtGui.QImage(60, 20,
                                 QtGui.QImage.Format.Format_ARGB32)
            image.fill(QtGui.QColor("#00000000"))
            painter = QtGui.QPainter(image)
            try:
                with_delegate.paint(painter, option, on_index)
            finally:
                painter.end()
            return image

        ours = render(delegate, index)
        theirs = render(plain, blank_model.index(0, 0))
        # The strip RIGHT of the mark: the tick sits at the left edge,
        # PAD in, and is at most SIDE wide.
        left = delegate.PAD + delegate.SIDE + 2
        sampled = 0
        for x in range(left, 60):
            for y in range(0, 20):
                sampled += 1
                self.assertEqual(
                    QtGui.QColor(theirs.pixel(x, y)).name(
                        QtGui.QColor.NameFormat.HexArgb),
                    QtGui.QColor(ours.pixel(x, y)).name(
                        QtGui.QColor.NameFormat.HexArgb),
                    "a selected tick cell is not decorated like every "
                    "other cell at (%d, %d) - the highlight band "
                    "breaks around it" % (x, y))
        self.assertTrue(sampled, "nothing was compared - not a test")

    def test_every_tick_column_actually_gets_a_tick_delegate(self):
        """The other direction from `test_a_YES_NO_column_is_a_TICK_
        column`: a column can be listed as a tick and still be drawn as
        text if nothing binds it."""
        table = self.panel.thumbtable
        bound = {
            key for column, key in enumerate(grid_columns.KEYS)
            if isinstance(table.itemDelegateForColumn(column),
                          delegates.TickCellDelegate)}
        missing = set(grid_columns.GridColumnsMixin.TICK_COLUMNS) - bound
        self.assertFalse(
            missing,
            "%s is listed as a tick but nothing draws one"
            % ", ".join(sorted(missing)))


class TheSortArrowIsPAIDFORByTheColumnThatHasIt(unittest.TestCase):
    """`setSortIndicatorShown(True)` makes a stock `QHeaderView`
    reserve room for the arrow in EVERY section, because any of them
    might become the sorted one.

    Measured 2026-08-04 at Houdini's 12pt: 21px each, so eight shown
    columns paid 147px for one arrow - and it fell hardest on the
    columns whose heading is all they hold. Favorite asked 80px to
    show a tick under the word "Favorite", 59 without it. That
    reservation, not the cell, is why those two columns kept reading
    as mis-sized.
    """

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def setUp(self):
        self.header = self.panel.thumbtable.horizontalHeader()

    def _shown(self):
        return [c for c in range(len(grid_columns.KEYS))
                if not self.panel.thumbtable.isColumnHidden(c)]

    def test_the_table_uses_the_header_that_knows_this(self):
        self.assertIsInstance(self.header, ui_helpers.GridHeaderView)

    def test_a_column_with_no_arrow_pays_nothing_for_one(self):
        """The IDENTITY, not Qt's arithmetic: a non-sorted section
        measures exactly what it would with the indicator switched
        off. If Qt ever changes how it reserves the space, this fails
        instead of quietly drifting."""
        header = self.header
        self.assertTrue(header.isSortIndicatorShown(),
                        "no indicator to reserve room for - not a test")
        sorted_section = header.sortIndicatorSection()
        with_arrow = {c: header.sectionSizeFromContents(c).width()
                      for c in self._shown()}
        header.setSortIndicatorShown(False)
        self.addCleanup(header.setSortIndicatorShown, True)
        without = {c: header.sectionSizeFromContents(c).width()
                   for c in self._shown()}
        for column, width in with_arrow.items():
            if column == sorted_section:
                continue
            with self.subTest(column=grid_columns.KEYS[column]):
                self.assertEqual(
                    without[column], width,
                    "%s reserves room for an arrow it never shows"
                    % grid_columns.KEYS[column])

    def test_the_SORTED_column_still_has_room_for_its_arrow(self):
        """Taking the room off every column would put the arrow on top
        of the heading of whichever one you sorted by."""
        header = self.header
        column = header.sortIndicatorSection()
        self.assertIn(
            column, self._shown(),
            "the sort arrow points at a HIDDEN column, so it is drawn "
            "nowhere and the list reads as unsorted")
        wide = header.sectionSizeFromContents(column).width()
        header.setSortIndicatorShown(False)
        self.addCleanup(header.setSortIndicatorShown, True)
        self.assertGreater(
            wide, header.sectionSizeFromContents(column).width(),
            "the column being sorted by has no room for its arrow")


class EveryCellHasAIREitherSide(unittest.TestCase):
    """Five pixels of air either side of a cell's text (2026-08-04).

    Through the STYLE's own metric, not a stylesheet. The first answer
    was `QTableView::item { padding-left: 5px; ... }` and it cost four
    unrelated things - the widget's font, the selection band's colour,
    the selected text's colour, and a second copy of each in the rule.
    """

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def setUp(self):
        panel = self.panel
        panel.section_tabs.setChecked("material")
        panel.prefs.view_mode = "list"
        panel.apply_view_mode()
        QtWidgets.QApplication.processEvents()
        self.addCleanup(panel.apply_view_mode)
        self.addCleanup(setattr, panel.prefs, "view_mode", "grid")

    def test_the_table_wears_NO_style_object(self):
        """A `QProxyStyle` handed to `setStyle` is owned by nobody: the
        widget does not take it and the bindings declare no `parent` or
        `reference-count` rule for that call, unlike `setHorizontalHeader`
        and `setItemDelegateForColumn` which declare both. The view kept
        a pointer to a freed object and the process bus-errored on
        teardown - three test classes fatal, and a live session left a
        signal-10 crash log on quit (2026-08-04)."""
        self.assertNotIsInstance(
            self.panel.thumbtable.style(), QtWidgets.QProxyStyle,
            "the table wears a style object again")

    def test_the_table_carries_NO_stylesheet(self):
        """A stylesheet hands item drawing to `QStyleSheetStyle`,
        whatever the rule names: the font resolves from the
        application default, the band is drawn with its own blend, and
        selected text comes out in the ORDINARY text colour rather
        than `HighlightedText`. Seen in the panel 2026-08-04: the band
        and the text both wrong while the tick marks were right - the
        ticks being the one thing that asks the palette by hand.
        """
        self.assertEqual(
            "", self.panel.thumbtable.styleSheet(),
            "the table carries a stylesheet again")

    def test_the_SELECTION_is_left_to_HOUDINI(self):
        """Nothing here paints or recolours a selected row any more.

        The panel puts `hou.qt.styleSheet()` on its own root and every
        child inherits it, so the table already carries Houdini's
        `QAbstractItemView::item:selected` - `ListEntrySelected`
        (SELECTION_BASE) blended toward the row, with the full colour
        as a hairline top and bottom, and `TextColor` for the text.
        Both from `config/UIDark.hcs`. A second opinion here is what
        made the list disagree with every other list in the host.

        Pinned as the ABSENCE of an override, not as a colour: the
        colour is Houdini's to change, and an offscreen render cannot
        see the app stylesheet anyway."""
        delegate = self.panel.thumbtable.itemDelegate()
        for name in ("_highlight", "_selected_text", "set_highlight"):
            self.assertFalse(
                hasattr(delegate, name),
                "the cell delegate owns %s again - the selection is "
                "the host's" % name)

    def test_the_band_is_the_GRIDS_highlight(self):
        panel = self.panel
        self.assertEqual(
            panel.thumblist.palette().color(
                QtGui.QPalette.ColorRole.Highlight).name(),
            panel.thumbtable.palette().color(
                QtGui.QPalette.ColorRole.Highlight).name(),
            "the table's selection is not the grid's own colour")

class GridModeCannotSeeAnyOfIt(unittest.TestCase):
    """The property the whole migration rests on."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def test_the_grid_view_shows_column_zero_only(self):
        self.assertEqual(
            0, self.panel.thumblist.modelColumn(),
            "the grid view is showing a column other than the row")

    def test_the_proxy_passes_the_columns_through(self):
        """A proxy that flattened them would leave the table with one
        column and no explanation."""
        self.panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        proxy = self.panel.thumblist.model()
        self.assertEqual(len(grid_columns.COLUMNS), proxy.columnCount(),
                         "the grid proxy dropped the columns")
        self.assertTrue(proxy.index(0, 3).isValid(),
                        "the proxy cannot address a later column")


class ARowRepaintCoversTheWholeROW(unittest.TestCase):
    """`dataChanged(index(row, 0), index(row, 0))` was the whole row
    when a row WAS one column. With ten it invalidates the thumbnail
    and nothing else, so every later cell keeps its old text until
    something unrelated forces a repaint.

    Fifteen emit sites read perfectly and were quietly half-right the
    moment the models gained columns - which is the kind of thing that
    would have shipped as "the Type column doesn't update" weeks later.
    `GridColumnsMixin.row_changed` is the one way to say it now.
    """

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def test_a_row_repaint_spans_every_column(self):
        model = self.panel.material_model
        if not model.rowCount():
            self.skipTest("no materials in the fixture")
        seen = []
        model.dataChanged.connect(
            lambda tl, br, roles=None: seen.append((tl.column(), br.column())))
        model.row_changed(0, [QtCore.Qt.ItemDataRole.DecorationRole])
        QtWidgets.QApplication.processEvents()
        self.assertTrue(seen, "row_changed emitted nothing")
        first, last = seen[0]
        self.assertEqual(0, first)
        self.assertEqual(
            len(grid_columns.COLUMNS) - 1, last,
            "a row repaint covers columns %d..%d of %d - the later "
            "cells will keep stale text"
            % (first, last, len(grid_columns.COLUMNS)))

    def test_no_model_still_emits_a_single_column_row_range(self):
        """Read as STRUCTURE: an emit whose topLeft and bottomRight are
        the same expression is a row repaint that covers one column."""
        import ast
        offenders = []
        for name in ("library", "code_library", "cop_library",
                     "file_library", "gradient_library", "matx_library"):
            path = os.path.join(PACKAGE, "core", "%s.py" % name)
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "emit"
                        and getattr(node.func.value, "attr", "")
                        == "dataChanged"):
                    continue
                if len(node.args) < 2:
                    continue
                if ast.unparse(node.args[0]) == ast.unparse(node.args[1]):
                    offenders.append("%s:%d" % (name, node.lineno))
        self.assertEqual(
            [], offenders,
            "these repaint one column and call it a row: %s - use "
            "row_changed()" % offenders)

    def test_a_finished_PREVIEW_repaints_its_row(self):
        """The one repaint path only the ONLINE model has: a download
        lands, the thumbnail engine says so, and the tile has to pick it
        up. No test ever ran it, so the one-argument `self.index(row)`
        sat in `_on_preview_ready` after the migration fixed the other
        61 sites - and every arriving preview raised `TypeError` where
        it should have repainted (12 of them in one live session,
        2026-08-05).
        """
        from amaze.core import matx_library, matx_sources

        model = matx_library.MatxOnlineLibrary.__new__(
            matx_library.MatxOnlineLibrary)
        # Signals only. The real __init__ starts threads and fetches.
        QtCore.QAbstractTableModel.__init__(model)
        record = matx_sources.MatxRecord(
            source="GPUOpen", uid="u0", title="M0", kind="package",
            payload={})
        key = model._preview_key(record)
        model._records = [record]
        model._key_rows = {key: 0}

        seen = []
        model.dataChanged.connect(
            lambda tl, br, roles=None: seen.append(
                (tl.row(), tl.column(), br.column(), list(roles or []))))
        model._on_preview_ready(key)

        self.assertTrue(
            seen,
            "a finished preview repainted NOTHING - the tile keeps its "
            "placeholder until some unrelated repaint happens to cover "
            "it")
        row, first, last, roles = seen[0]
        self.assertEqual(0, row, "the wrong row was repainted")
        self.assertEqual(0, first)
        self.assertEqual(
            len(grid_columns.COLUMNS) - 1, last,
            "the preview repaint covers columns %d..%d of %d"
            % (first, last, len(grid_columns.COLUMNS)))
        self.assertIn(
            QtCore.Qt.ItemDataRole.DecorationRole, roles,
            "the repaint does not name the role that CHANGED, so a "
            "view filtering on roles will ignore it")

    def test_no_TABLE_model_builds_a_ONE_ARGUMENT_index(self):
        """`QAbstractTableModel.index(row)` will not take one argument:
        the list base defaults the column, the table base requires it
        (research.md ▸ Qt widgets, views & painting).

        The migration swept 62 call sites and fixed 61. The 62nd was
        `matx_library._on_preview_ready`, on the one path no test ran -
        and NOTHING in the suite held the fact, so a 63rd would be
        exactly as invisible. This holds it.

        Read as STRUCTURE, off the BASE CLASS rather than the file: a
        one-argument `index(row)` on a `QAbstractListModel` is correct
        and stays untouched (`folders.py` has one), and a subclass that
        reaches the table base through another class - `CopLibrary` via
        `MaterialLibrary` - is still a table model.
        """
        import ast

        classes = []
        for root, dirs, files in os.walk(PACKAGE):
            dirs[:] = [d for d in dirs
                       if d not in ("tests", "__pycache__")]
            for name in sorted(files):
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                with open(path, encoding="utf-8") as handle:
                    tree = ast.parse(handle.read())
                classes.extend(
                    (path, node) for node in ast.walk(tree)
                    if isinstance(node, ast.ClassDef))

        table = set()
        changed = True
        while changed:
            changed = False
            for _path, node in classes:
                if node.name in table:
                    continue
                bases = {b.attr if isinstance(b, ast.Attribute)
                         else getattr(b, "id", "") for b in node.bases}
                if "QAbstractTableModel" in bases or bases & table:
                    table.add(node.name)
                    changed = True

        self.assertIn(
            "MatxOnlineLibrary", table,
            "the base-class walk found no table models at all, so this "
            "test would pass against anything")

        offenders = []
        for path, node in classes:
            if node.name not in table:
                continue
            for call in ast.walk(node):
                if not (isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "index"
                        and isinstance(call.func.value, ast.Name)
                        and call.func.value.id == "self"):
                    continue
                if len(call.args) == 1 and not call.keywords:
                    offenders.append(
                        "%s:%d in %s" % (os.path.basename(path),
                                         call.lineno, node.name))
        self.assertEqual(
            [], offenders,
            "a table model cannot index a row without naming a column - "
            "each of these raises TypeError the moment it runs: %s"
            % offenders)


class TheTableViewIsWiredToTheSameEVERYTHING(unittest.TestCase):
    """Step 2b: list mode shows a real `QTableView`.

    A second VIEW, not a second area. It shares the model, the proxy
    and the SELECTION MODEL with the grid - which is what stops list
    mode doubling every area binding - and only one is visible.
    """

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _mode(self, mode):
        self.panel.prefs.view_mode = mode
        self.panel.apply_view_mode()
        QtWidgets.QApplication.processEvents()

    def setUp(self):
        self.panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        self.addCleanup(self._mode, "grid")

    def test_both_views_share_one_model_and_one_selection(self):
        """Two views over one selection model is Qt's own arrangement,
        and it is the whole reason this does not double the bindings."""
        panel = self.panel
        self.assertIs(panel.thumblist.model(), panel.thumbtable.model())
        self.assertIs(panel.thumblist.selectionModel(),
                      panel.thumbtable.selectionModel())

    def test_selecting_in_one_selects_in_the_other(self):
        panel = self.panel
        proxy = panel.thumblist.model()
        self.assertTrue(proxy.rowCount(), "no rows to select")
        panel.thumblist.selectionModel().select(
            proxy.index(0, 0),
            QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.assertTrue(
            panel.thumbtable.selectionModel().selectedIndexes(),
            "the table has its own selection - they will drift")

    def test_exactly_one_view_is_up_in_each_mode(self):
        panel = self.panel
        panel.show()
        self.addCleanup(panel.hide)
        self._mode("list")
        self.assertTrue(panel.thumbtable.isVisible())
        self.assertFalse(panel.thumblist.isVisible())
        self._mode("grid")
        self.assertFalse(panel.thumbtable.isVisible())
        self.assertTrue(panel.thumblist.isVisible())

    def test_the_painted_STRIP_no_longer_exists(self):
        """`ListColumnHeader` was a strip painted above the rows, told
        the column widths by hand and told again whenever the rows
        scrolled sideways - or its labels named whichever column had
        slid underneath them. A QHeaderView IS the view's header: it
        cannot disagree with its rows and it scrolls with them.

        Retired with the fit that fed it (2026-08-04). The panel no
        longer builds one at all, which is what this pins - a second
        header coming back is a second answer to where a column is.
        """
        self.assertFalse(
            hasattr(self.panel, "list_header"),
            "the panel builds a painted column strip again, beside a "
            "real header")
        self.assertFalse(
            hasattr(ui_helpers, "ListColumnHeader"),
            "the painted strip's class is back - 178 lines that only "
            "a second header could need")

    def test_the_table_does_NOT_wear_the_tile_delegate(self):
        """That delegate paints a whole TILE per index. On a table a
        row is ten indexes, and the first render put ten tile-height
        cells side by side."""
        panel = self.panel
        self.assertIsNot(panel.thumbtable.itemDelegate(),
                         panel.thumblist.itemDelegate())

    def test_LIST_MODE_HAS_NO_PICTURE_COLUMN(self):
        """Decided 2026-08-04: list mode shows no thumbnail at all -
        the cleaner answer to the slowness by a distance.

        At list size a thumbnail is 16px, the same argument that took
        the BADGES out of list rows days earlier. Removing it also
        removes the reason column measuring was expensive:
        DecorationRole is never asked for in list mode now, so nothing
        queues a picture the user cannot see. Measured across the
        three states: 1668 reads, then 18, now none.
        """
        self._mode("list")
        self.assertTrue(
            self.panel.thumbtable.isColumnHidden(
                grid_columns.KEYS.index("thumb")),
            "list mode is showing a thumbnail column again")

    def test_a_column_this_section_cannot_fill_is_HIDDEN(self):
        """Materials has no open-scene role, so there is no Open
        column - the same answer the painted strip gave by drawing
        nothing."""
        panel = self.panel
        self._mode("list")
        self.assertTrue(
            panel.thumbtable.isColumnHidden(
                grid_columns.KEYS.index("open")),
            "Materials shows an Open column it can never fill")
        self.assertFalse(
            panel.thumbtable.isColumnHidden(
                grid_columns.KEYS.index("name")))

    def test_the_row_is_one_text_line_not_a_tile(self):
        """`activate()` can run in GRID mode, where the thumb size is
        the slider's 128 - reading it there gave 133px rows."""
        panel = self.panel
        self._mode("list")
        # A TEXT LINE, since the picture column went: the row used to
        # be sized to fit a 16px thumbnail and there is no thumbnail in
        # it now.
        metrics = QtGui.QFontMetrics(panel.thumblist.font())
        height = panel.thumbtable.verticalHeader().defaultSectionSize()
        self.assertLess(
            height, metrics.height() + theme.ui_px(12),
            "the row is taller than a line of text needs")
        self.assertGreaterEqual(height, metrics.height())

    def test_the_table_wears_the_panels_own_colours(self):
        """A QTableView brings the platform palette - white rows and
        black text against a dark panel."""
        panel = self.panel
        panel.show()
        self.addCleanup(panel.hide)
        self._mode("list")
        self.assertEqual(panel.thumblist.palette().base().color(),
                         panel.thumbtable.palette().base().color())
        self.assertEqual(panel.thumblist.font().pointSizeF(),
                         panel.thumbtable.font().pointSizeF())


class TheHeaderSORTS(unittest.TestCase):
    """What the painted strip could never do, and the reason the whole
    migration was worth its cost: click a heading and the rows reorder
    by that column.

    It needs nothing new. Every column answers DisplayRole with its own
    text (the mixin), and QSortFilterProxyModel compares exactly that
    for whichever column it is asked about.
    """

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def setUp(self):
        panel = self.panel
        panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        panel.prefs.view_mode = "list"
        panel.apply_view_mode()
        QtWidgets.QApplication.processEvents()
        self.addCleanup(self._back_to_grid)

    def _back_to_grid(self):
        self.panel.prefs.view_mode = "grid"
        self.panel.apply_view_mode()
        QtWidgets.QApplication.processEvents()

    def _column(self, key):
        proxy = self.panel.thumbtable.model()
        index = grid_columns.KEYS.index(key)
        return [proxy.index(row, index).data()
                for row in range(proxy.rowCount())]

    def test_the_table_offers_sorting_at_all(self):
        self.assertTrue(self.panel.thumbtable.isSortingEnabled())

    def test_sorting_by_a_column_orders_by_THAT_column(self):
        panel = self.panel
        column = grid_columns.KEYS.index("category")
        panel.thumbtable.sortByColumn(
            column, QtCore.Qt.SortOrder.AscendingOrder)
        QtWidgets.QApplication.processEvents()
        values = [v for v in self._column("category") if v]
        self.assertTrue(values, "no categories to sort")
        self.assertEqual(
            sorted(values, key=str.lower), values,
            "sorting by Category did not order by category: %s" % values)

    def test_the_order_REVERSES(self):
        panel = self.panel
        column = grid_columns.KEYS.index("name")
        panel.thumbtable.sortByColumn(
            column, QtCore.Qt.SortOrder.AscendingOrder)
        QtWidgets.QApplication.processEvents()
        up = [v for v in self._column("name") if v]
        panel.thumbtable.sortByColumn(
            column, QtCore.Qt.SortOrder.DescendingOrder)
        QtWidgets.QApplication.processEvents()
        down = [v for v in self._column("name") if v]
        self.assertEqual(up, list(reversed(down)),
                         "the second click did not reverse the order")

    def test_a_chosen_column_survives_a_FILTER_change(self):
        """`setDynamicSortFilter(False)` turns off the re-sort after a
        filter change - GridProxyModel puts it back, reading
        `sortColumn()`. If it read 0 instead, a user's chosen column
        would snap back to name on the next keystroke."""
        panel = self.panel
        column = grid_columns.KEYS.index("category")
        panel.thumbtable.sortByColumn(
            column, QtCore.Qt.SortOrder.AscendingOrder)
        QtWidgets.QApplication.processEvents()
        panel._section().filter_text("a")
        QtWidgets.QApplication.processEvents()
        self.addCleanup(panel._section().filter_text, "")
        self.assertEqual(
            column, panel.thumbtable.model().sortColumn(),
            "the filter change reset the sort column")


class TheSelectionSpeaksInROWS(unittest.TestCase):
    """List mode selects whole ROWS; every consumer sees ONE index per
    row, at column 0.

    research.md ▸ *Row selection over a table view* (measured): a
    SelectRows selection answers `selectedIndexes()` with one index PER
    CELL - ten for one selected row, the hidden thumb column included -
    and the current index keeps whichever column the click landed on.
    Left raw, one selected row greys every needs-one menu entry, labels
    read "Delete (10)", and Favorite toggles the same asset ten times -
    an even number, so the star appears dead. The collapse to column 0
    lives at the chokepoints (`grid_columns.selected_rows`,
    `ui_helpers.live_current_index`); these tests select through the
    table the way a CLICK does and hold it there.
    """

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def setUp(self):
        panel = self.panel
        panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        panel.prefs.view_mode = "list"
        panel.apply_view_mode()
        QtWidgets.QApplication.processEvents()
        self.addCleanup(self._back_to_grid)

    def _back_to_grid(self):
        self.panel.prefs.view_mode = "grid"
        self.panel.apply_view_mode()
        QtWidgets.QApplication.processEvents()

    def _select_row(self, row):
        """Select the way a CLICK does: current lands on a VISIBLE cell
        (the thumb column is hidden, so no click can land on column 0),
        the selection spans the row."""
        proxy = self.panel.thumbtable.model()
        selection = self.panel.thumbtable.selectionModel()
        flags = (QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect
                 | QtCore.QItemSelectionModel.SelectionFlag.Rows)
        name_column = grid_columns.KEYS.index("name")
        selection.setCurrentIndex(proxy.index(row, name_column), flags)
        QtWidgets.QApplication.processEvents()
        return proxy

    def test_one_selected_row_is_ONE_grid_selection(self):
        self._select_row(0)
        selection = self.panel._section().grid_selection()
        self.assertEqual(
            1, len(selection),
            "one selected row reads as %d selections" % len(selection))
        self.assertEqual(0, selection[0].column(),
                         "the selection does not speak in column 0")

    def test_favourite_toggles_ONCE_for_one_row(self):
        proxy = self._select_row(0)
        model = self.panel.material_model
        row = proxy.mapToSource(proxy.index(0, 0)).row()

        def fav():
            return bool(model.data(model.index(row, 0),
                                   model.FavoriteRole))

        before = fav()
        section = self.panel._section()
        section.toggle_favourite(section.grid_selection())
        self.assertNotEqual(
            before, fav(),
            "the toggle ran an even number of times - ten, one per "
            "column - and the star ends where it began")

    def test_assign_category_MOVES_the_selected_asset(self):
        """The Move-to menu and the sidebar drop both land here, and
        both were dead: a one-argument `index(row)` on a table model
        raises TypeError before any row is edited."""
        proxy = self._select_row(0)
        model = self.panel.material_model
        row = proxy.mapToSource(proxy.index(0, 0)).row()
        self.panel.assign_category_active("Seam Test")
        self.assertIn(
            "Seam Test",
            model.data(model.index(row, 0), model.CategoryRole),
            "Move to a category changed nothing")

    def test_the_details_form_shows_ONE_value_for_one_row(self):
        self._select_row(0)
        self.panel.update_details_view()
        self.assertNotEqual(
            "Multiple Values...", self.panel.line_name.text(),
            "one selected row reads as a multi-selection in the form")

    def test_update_info_WRITES_the_edit(self):
        """The Edit Info dialog's Update path - the second shipped
        one-argument `index(row)`."""
        proxy = self._select_row(0)
        model = self.panel.material_model
        row = proxy.mapToSource(proxy.index(0, 0)).row()
        self.panel.update_details_view()          # populate the form
        self.panel.line_name.setText("Renamed By Seam")
        self.panel.user_update_asset()
        self.assertEqual(
            "Renamed By Seam", model.assets[row].name,
            "Update Info wrote nothing")

    def test_a_dragged_column_width_survives_a_tab_switch(self):
        """Widths are DEFAULTS the user can drag (overview.md §2) - but
        the seed ran on every activate and view-mode switch, so a
        dragged column snapped back to its default on the next tab
        click. The seed runs once per view; later syncs change
        visibility only."""
        panel = self.panel
        header = panel.thumbtable.horizontalHeader()
        column = grid_columns.KEYS.index("name")
        dragged = header.sectionSize(column) + 77
        header.resizeSection(column, dragged)
        panel.section_tabs.setChecked("code")
        QtWidgets.QApplication.processEvents()
        panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        self.assertEqual(
            dragged, header.sectionSize(column),
            "the tab switch re-seeded the default over the user's drag")

    def test_recategorising_a_selection_is_TWO_index_writes(self):
        """One for the new category, ONE for the whole selection - not
        one per row plus one per row's tag check: each index write
        serialises and hashes the full 548-row document, and a 50-tile
        Move-to paid it a hundred times."""
        from unittest import mock

        from amaze.helpers import hostos as hostos_mod

        self._select_row(0)
        writes = []
        real = hostos_mod.write_json_atomic

        def counting(path, *args, **kwargs):
            if str(path).endswith("library.json"):
                writes.append(str(path))
            return real(path, *args, **kwargs)

        with mock.patch.object(hostos_mod, "write_json_atomic",
                               counting):
            self.panel.assign_category_active("One Write")
        self.assertEqual(
            2, len(writes),
            "recategorising one row wrote the index %d times"
            % len(writes))

    def test_the_table_offers_the_menu_and_the_primary_action(self):
        """`thumblist` gets both wirings; the table got neither, so in
        list mode right-click opened nothing and double-click did
        nothing - the whole GRID_MENU unreachable in one of the two
        view modes."""
        table = self.panel.thumbtable

        def connected(signal):
            return table.isSignalConnected(
                QtCore.QMetaMethod.fromSignal(signal))

        self.assertEqual(
            QtCore.Qt.ContextMenuPolicy.CustomContextMenu,
            table.contextMenuPolicy(),
            "right-click on a list row opens nothing")
        self.assertTrue(connected(table.customContextMenuRequested),
                        "the menu request goes nowhere")
        self.assertTrue(connected(table.doubleClicked),
                        "double-click performs no primary action")


class TheCallersNameTheColumnToo(unittest.TestCase):
    """test_no_TABLE_model_builds_a_ONE_ARGUMENT_index holds the fact
    INSIDE the model classes; this is the callers' half. Both shipped
    instances were in panel.py - the Move-to path and the Edit Info
    Update path, exactly the verbs nothing drove - and both raise
    TypeError the moment they run, because every grid model is a table
    now."""

    def test_no_panel_caller_builds_a_ONE_ARGUMENT_index(self):
        import ast

        offenders = []
        panel_dir = os.path.join(PACKAGE, "panel")
        for name in sorted(os.listdir(panel_dir)):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(panel_dir, name),
                      encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "index"
                        and len(node.args) == 1
                        and not node.keywords):
                    continue
                receiver = node.func.value
                tail = ""
                if isinstance(receiver, ast.Attribute):
                    tail = receiver.attr
                elif isinstance(receiver, ast.Name):
                    tail = receiver.id
                if "model" in tail.lower():
                    offenders.append("%s:%d" % (name, node.lineno))
        self.assertEqual(
            [], offenders,
            "a table model cannot index a row without naming a column - "
            "each of these raises TypeError the moment it runs: %s"
            % offenders)


if __name__ == "__main__":
    unittest.main()
