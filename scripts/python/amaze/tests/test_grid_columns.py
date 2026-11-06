"""The grid models are table models; column 0 answers as before. ▸p/grid-columns-migration"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze import amazetheme  # noqa: E402
from amaze.core import grid_columns, grid_engine  # noqa: E402
from amaze.panel import delegates, grid  # noqa: E402
from amaze.helpers import theme, ui_helpers  # noqa: E402
from amaze.tests import test_support  # noqa: E402

PACKAGE = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))

GRID_MODELS = (   # (section key, panel attribute) for every model the Grid shows
    ("material", "material_model"),
    ("cop", "cop_model"),
    ("code", "code_model"),
    ("file", "file_files_model"),
    ("gradient", "gradient_model"),
)


class ThereIsONEColumnOrder(unittest.TestCase):

    def test_every_model_reads_the_SAME_list(self):
        """The order lives in `core`: models importing `ui_helpers` would cycle via `core.debug`."""
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

    def test_every_grid_model_is_a_TABLE_model_with_the_shared_columns(self):
        """A list model refuses column > 0; the header is shared, so the counts must agree."""
        for key, model in self._models():
            with self.subTest(section=key):
                self.assertIsInstance(model, QtCore.QAbstractTableModel)
                self.assertIsInstance(model, grid_engine.GridEngine)
                self.assertEqual(len(grid_columns.COLUMNS), model.columnCount())

    def test_an_index_in_a_LATER_column_is_valid(self):
        """The whole point, and the thing the old base made impossible."""
        for key, model in self._models():
            with self.subTest(section=key):
                index = model.index(0, 3)
                self.assertTrue(index.isValid(),
                                "%s cannot address column 3" % key)
                self.assertEqual(3, index.column())

    def test_COLUMN_ZERO_answers_exactly_what_it_used_to(self):
        """Grid mode reads column 0 and nothing else, so it must answer exactly as before."""
        display = QtCore.Qt.ItemDataRole.DisplayRole
        for key, model in self._models():
            with self.subTest(section=key):
                named = [row for row in range(min(model.rowCount(), 40))
                         if model.index(row, 0).data(display)]  # a named row: the material fixture's row 0 has an empty name on purpose
                self.assertTrue(named, "%s has no named row to check" % key)
                index = model.index(named[0], 0)
                self.assertTrue(index.data(display))
                role = getattr(model, "FavoriteRole", None)  # a UserRole the grid delegate reads still answers on column 0
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
        """Color has no Tags and File has no Version: the column is absent from its map."""
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
        """Categories and tags are lists on the record; a cell shows them joined as text."""
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
        """Decoration and the rest answer on column 0 only, or the thumbnail lands in all ten."""
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
    """How a cell reads, answered by model roles and Qt metrics rather than by a painter."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _column(self, key):
        return grid_columns.KEYS.index(key)

    def test_the_CATEGORY_is_written_in_the_CATEGORYS_OWN_COLOUR(self):
        """The colour the user gave that category, the same one the grid paints under its tiles."""
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
        for key in ("name", "type", "tags", "license"):
            with self.subTest(column=key):
                self.assertIsNone(
                    model.index(row, self._column(key)).data(
                        QtCore.Qt.ItemDataRole.ForegroundRole),
                    "%s coloured itself - only Category does" % key)

    def _colour_a_category(self, colour):
        """Give one category a colour and return the row wearing it; the fixture ships none coloured."""
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

    def test_a_row_whose_category_has_NO_colour_asks_for_none(self):
        """No colour is not black: an invalid QColor for `ForegroundRole` still paints the text."""
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

    def test_NO_column_overrides_the_views_font_or_alignment(self):
        """A role-supplied font replaces the view's family; a centred tick reads as another table."""
        model = self.panel.material_model
        if not model.rowCount():
            self.skipTest("no materials in the fixture")
        text = ("name", "type", "category", "tags")
        for key in text + grid_engine.GridEngine.TICK_COLUMNS:
            roles = [QtCore.Qt.ItemDataRole.TextAlignmentRole]
            if key in text:
                roles.append(QtCore.Qt.ItemDataRole.FontRole)
            for role in roles:
                with self.subTest(column=key, role=role):
                    self.assertIsNone(model.index(0, self._column(key)).data(role))

    def _every_model(self):
        panel = self.panel
        for key in ("material_model", "gradient_model", "node_model"):
            model = getattr(panel, key, None)
            if model is not None and model.rowCount():
                yield key, model


class ATickColumnIsAsWideAsTheTICK(unittest.TestCase):
    """`ResizeToContents` measures `DisplayRole`, whose raw yes/no is kept for the sort, not drawn."""

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
        """A selected tick cell paints the band as a plain cell does, beside the mark."""
        table = self.panel.thumbtable
        column = grid_columns.KEYS.index("favorite")
        delegate = table.itemDelegateForColumn(column)
        index = table.model().index(0, column)
        blank_model = QtGui.QStandardItemModel()  # a plain cell with no text, which is what a tick cell is
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
        left = delegate.PAD + delegate.SIDE + 2  # the strip RIGHT of the mark: the tick sits at the left edge, PAD in, and is at most SIDE wide
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
        """A column listed as a tick is still drawn as text if nothing binds its delegate."""
        table = self.panel.thumbtable
        bound = {
            key for column, key in enumerate(grid_columns.KEYS)
            if isinstance(table.itemDelegateForColumn(column),
                          delegates.TickCellDelegate)}
        missing = set(grid_engine.GridEngine.TICK_COLUMNS) - bound
        self.assertFalse(
            missing,
            "%s is listed as a tick but nothing draws one"
            % ", ".join(sorted(missing)))


class TheSortArrowIsPAIDFORByTheColumnThatHasIt(unittest.TestCase):
    """A stock `QHeaderView` reserves sort-arrow room in every section; ours only in the sorted one."""

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
        """An unsorted section measures exactly what it would with the indicator off."""
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
        """Without room in the sorted column, the arrow would sit on top of its heading."""
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
    """Cell text sits at L01's inset, drawn by the delegate: no stylesheet, no style object."""

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

    def test_the_table_wears_NO_style_object_and_NO_stylesheet(self):
        """An unowned QProxyStyle bus-errored on teardown; a stylesheet takes over item drawing."""
        self.assertNotIsInstance(
            self.panel.thumbtable.style(), QtWidgets.QProxyStyle,
            "the table wears a style object again")
        self.assertEqual(
            "", self.panel.thumbtable.styleSheet(),
            "the table carries a stylesheet again")

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
        """A proxy that flattened them would leave the table with one column and no explanation."""
        self.panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        proxy = self.panel.thumblist.model()
        self.assertEqual(len(grid_columns.COLUMNS), proxy.columnCount(),
                         "the grid proxy dropped the columns")
        self.assertTrue(proxy.index(0, 3).isValid(),
                        "the proxy cannot address a later column")


class ARowRepaintCoversTheWholeROW(unittest.TestCase):
    """A row repaint spans every column; `GridColumnsMixin.row_changed` is the one way to say it."""

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
        """Read as structure: an emit with the same topLeft and bottomRight covers one column."""
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
        """The online model repaints a row when a downloaded preview lands, without raising."""
        from amaze.core import matx_library, matx_sources

        model = matx_library.MatxOnlineLibrary.__new__(
            matx_library.MatxOnlineLibrary)
        QtCore.QAbstractTableModel.__init__(model)  # signals only: the real __init__ starts threads and fetches
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
        """`QAbstractTableModel.index` requires the column; read off the base class, not the file."""
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
    """List mode is a second view sharing the grid's model, proxy and selection model."""

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

    def test_selecting_in_one_selects_in_the_other(self):
        """Two views over one model and one selection model, so the bindings are not doubled."""
        panel = self.panel
        self.assertIs(panel.thumblist.model(), panel.thumbtable.model())
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


    def test_the_table_does_NOT_wear_the_tile_delegate(self):
        """That delegate paints a whole tile per index, and a table row is ten indexes."""
        panel = self.panel
        self.assertIsNot(panel.thumbtable.itemDelegate(),
                         panel.thumblist.itemDelegate())

    def test_LIST_MODE_HAS_NO_PICTURE_COLUMN(self):
        """List mode shows no thumbnail, so `DecorationRole` is never asked for and nothing queues."""
        self._mode("list")
        self.assertTrue(
            self.panel.thumbtable.isColumnHidden(
                grid_columns.KEYS.index("thumb")),
            "list mode is showing a thumbnail column again")

    def test_a_column_this_section_cannot_fill_is_HIDDEN(self):
        """Materials has no open-scene role, so there is no Open column."""
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
        """The row is a text line, not the thumb size `activate()` may read in grid mode."""
        panel = self.panel
        self._mode("list")
        metrics = QtGui.QFontMetrics(panel.thumblist.font())  # a text line, since list rows hold no thumbnail
        height = panel.thumbtable.verticalHeader().defaultSectionSize()
        self.assertLess(
            height, metrics.height() + theme.ui_px(12),
            "the row is taller than a line of text needs")
        self.assertGreaterEqual(height, metrics.height())

    def test_the_table_wears_the_panels_own_colours(self):
        """A QTableView brings the platform palette - white rows and black text against a dark panel."""
        panel = self.panel
        panel.show()
        self.addCleanup(panel.hide)
        original = QtGui.QFont(panel.thumblist.font())
        self.addCleanup(panel.thumblist.setFont, original)
        distinctive = QtGui.QFont(original)
        distinctive.setPointSizeF(17.5)    # set HERE, so no font an earlier module left can stand in
        panel.thumblist.setFont(distinctive)
        self._mode("list")
        self.assertEqual(panel.thumblist.palette().base().color(),
                         panel.thumbtable.palette().base().color())
        self.assertEqual(17.5, panel.thumbtable.font().pointSizeF(),
                         "the table does not wear the grid's font")


class TheHeaderSORTS(unittest.TestCase):
    """A heading click sorts by that column: the proxy compares each column's `DisplayRole`."""

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

    def test_sorting_by_a_column_orders_by_THAT_column(self):
        panel = self.panel
        self.assertTrue(panel.thumbtable.isSortingEnabled())
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
        """A filter keystroke must not snap the user's chosen column back to Name."""
        panel = self.panel
        column = grid_columns.KEYS.index("category")
        panel.thumbtable.sortByColumn(
            column, QtCore.Qt.SortOrder.AscendingOrder)
        QtWidgets.QApplication.processEvents()
        panel._section().filter_text("a")
        QtWidgets.QApplication.processEvents()
        self.addCleanup(panel._section().filter_text, "")
        self.assertEqual(
            column, panel.thumbtable.model().sourceModel().sort_column(),
            "the filter change reset the sort column")
        self.assertEqual(
            column, panel.thumbtable.horizontalHeader().sortIndicatorSection(),
            "the arrow left the sorted column")


class TheSelectionSpeaksInROWS(unittest.TestCase):
    """List mode selects whole rows; every consumer sees one index per row, at column 0."""

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
        """Select as a click does: current on a visible cell, never hidden column 0; the row spans."""
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
        """The Move-to menu and the sidebar drop both land here, and must edit the row."""
        proxy = self._select_row(0)
        model = self.panel.material_model
        row = proxy.mapToSource(proxy.index(0, 0)).row()
        self.panel.assign_category_active("Seam Test")
        self.assertIn(
            "Seam Test",
            model.data(model.index(row, 0), model.CategoryRole),
            "Move to a category changed nothing")

    def test_a_rename_through_the_model_WRITES_the_edit(self):
        """The rename path of D01 and D02 writes the edit through the table model."""
        proxy = self._select_row(0)
        model = self.panel.material_model
        row = proxy.mapToSource(proxy.index(0, 0)).row()
        self.assertTrue(model.set_tile_name(row, "Renamed By Seam"))
        self.assertEqual(
            "Renamed By Seam", model.assets[row].name,
            "the rename wrote nothing")

    def test_a_dragged_column_width_survives_a_tab_switch(self):
        """Widths are seeded once per view; later syncs change visibility only."""
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
        """One for the new category, one for the whole selection: each write hashes the full index."""
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
        """The table gets the context menu and double-click wiring that `thumblist` has."""
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
    """The callers half: no panel code calls a one-argument `index` on a table model."""

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


class AColumnIsShownONLYIfTheModelCanFillIt(unittest.TestCase):
    """A column shows only when the model's `COLUMN_ROLES` fills it, not by the delegate's roles."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _activate(self, key):
        """The table's column state is the active section's, so activate the one under test."""
        kept = self.panel.current_section
        if kept != key:
            self.addCleanup(self.panel.section_tabs.setChecked, kept)
        self.panel.section_tabs.setChecked(key)
        QtWidgets.QApplication.processEvents()
        self.assertEqual(key, self.panel.current_section,
                         "the panel did not switch to %s" % key)

    def test_a_shown_column_is_one_the_model_answers(self):
        for section, model_attr in (("file", "file_files_model"),
                                    ("material", "material_model"),
                                    ("gradient", "gradient_model")):
            self._activate(section)
            model = getattr(self.panel, model_attr)
            for key in ("category", "tags", "license", "version", "open"):
                column = grid_columns.KEYS.index(key)
                can_fill = model._column_role(key) is not None
                shown = not self.panel.thumbtable.isColumnHidden(column)
                if shown and not can_fill:
                    self.fail(
                        "the %s section shows a %r column its model can "
                        "never fill - it has a heading, it sorts, it "
                        "takes the width, and every cell is empty"
                        % (section, key))

    def test_the_model_is_what_decides(self):
        """Source-derived: one source of truth, or they drift again."""
        import inspect
        from amaze.panel import grid as grid_module
        source = inspect.getsource(grid_module.sync_table_columns)
        self.assertIn(
            "_column_role", source,
            "column visibility is still decided without asking the "
            "model whether it can fill the column")


class TheCellDelegatesDoNotACCUMULATE(unittest.TestCase):
    """`setItemDelegate*` takes no ownership, so each `activate()` must drop its old delegates."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _live(self):
        """Delegates still on the table after a flush; `processEvents()` skips `DeferredDelete`."""
        app = QtWidgets.QApplication.instance()
        app.processEvents()
        app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        return [child for child in self.panel.thumbtable.children()
                if isinstance(child, QtWidgets.QAbstractItemDelegate)]

    def test_rebinding_does_not_grow_the_delegate_count(self):
        delegate = self.panel.thumblist.itemDelegate()
        grid.bind_table_cell_delegates(self.panel, delegate)
        first = len(self._live())
        for _ in range(4):
            grid.bind_table_cell_delegates(self.panel, delegate)
        self.assertLessEqual(
            len(self._live()), first,
            "four more binds left more delegates alive than one did - "
            "each tab switch leaks the set it replaced")

    def test_the_table_still_has_its_delegates_afterwards(self):
        """Dropping the old set keeps the live one, or the cells stop painting."""
        delegate = self.panel.thumblist.itemDelegate()
        grid.bind_table_cell_delegates(self.panel, delegate)
        self._live()
        keys = grid_columns.KEYS
        cell = self.panel.thumbtable.itemDelegateForColumn(
            keys.index("category"))
        self.assertIsNotNone(
            cell, "the category cell has no delegate, so it paints as text")
        self.assertIsNotNone(
            cell.parent(),
            "the live delegate is unparented, so nothing keeps it alive "
            "while the table still points at it")


class TheHeaderTakesTheClick(unittest.TestCase):
    """A replacement QHeaderView is not made clickable by `setSortingEnabled(True)` (Qt 6.8.3)."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def setUp(self):
        self.header = self.panel.thumbtable.horizontalHeader()

    def test_the_sections_answer_the_pointer(self):
        self.assertTrue(
            self.header.sectionsClickable(),
            "the header shows a sort arrow but no section takes a "
            "click, so the promise in the strip is a lie")

    def test_a_sort_indicator_change_reorders_the_rows(self):
        """The indicator drives the proxy: pointing it the other way reorders the table."""
        name_col = grid_columns.KEYS.index("name")
        model = self.panel.thumbtable.model()
        self.assertGreater(model.rowCount(), 1,
                           "one row cannot witness an order")
        original = (self.header.sortIndicatorSection(),
                    self.header.sortIndicatorOrder())
        self.addCleanup(self.header.setSortIndicator, *original)
        self.header.setSortIndicator(
            name_col, QtCore.Qt.SortOrder.DescendingOrder)
        descending = [model.index(r, name_col).data()
                      for r in range(model.rowCount())]
        self.assertEqual(
            sorted(descending, key=str.lower, reverse=True), descending,
            "the arrow flipped and the rows did not")


class TheListStandsOnItsFrame(unittest.TestCase):
    """The list's header, widths and tick boxes land where L01 draws them. ▸r/list-from-frame"""

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
        self.px = theme.ui_px
        self.column = self._by_key("column")
        self.heading = self._by_key("heading")
        self.table = panel.thumbtable
        self.header = self.table.horizontalHeader()

    def _by_key(self, kind):
        return amazetheme.drawn_by_owner("L01", kind)

    def test_the_frame_is_one_table_the_code_can_follow(self):
        """Columns in the table's order, edge to edge; one heading inset; one tick inset."""
        self.assertEqual([k for k in grid_columns.KEYS if k != "thumb"],
                         list(self.column))
        x = 0
        for key, node in self.column.items():
            self.assertEqual(x, node[1], "%s is not where the column before it ends" % key)
            x += node[3]
        self.assertEqual(1, len({n[4] for n in self.column.values()}),
                         "the headings are drawn at different heights")
        insets = {self.heading[k][1] - n[1] for k, n in self.column.items()}
        self.assertEqual(1, len(insets), "the headings sit at insets %s" % sorted(insets))
        ticks = {n[1] - self.column[amazetheme.drawn_name(n)[1]][1]
                 for n in amazetheme.drawn_nodes("L01", "tick box")}
        self.assertEqual(1, len(ticks), "the ticks sit at insets %s" % sorted(ticks))
        texts = {n[1] - self.column[amazetheme.drawn_name(n)[1]][1]
                 for n in amazetheme.drawn_nodes("L01", "cell")}
        self.assertEqual(1, len(texts), "the row texts sit at insets %s" % sorted(texts))

    def _render(self, delegate, index, selected=False):
        option = QtWidgets.QStyleOptionViewItem()
        self.table.initViewItemOption(option)
        row = amazetheme.drawn_node("L01", "row")
        option.rect = QtCore.QRect(0, 0, self.px(self.column["name"][3]), self.px(row[4]))
        if selected:
            option.state |= QtWidgets.QStyle.StateFlag.State_Selected
        image = QtGui.QImage(option.rect.size(), QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtGui.QColor("#ff00ff"))
        painter = QtGui.QPainter(image)
        try:
            delegate.paint(painter, option, index)
        finally:
            painter.end()
        return image

    @staticmethod
    def _ink_left(image):
        ground = image.pixelColor(1, 1)
        for x in range(image.width()):
            for y in range(image.height()):
                c = image.pixelColor(x, y)
                if (abs(c.red() - ground.red()) + abs(c.green() - ground.green())
                        + abs(c.blue() - ground.blue())) > 90:
                    return x
        return None

    def _name_cell(self):
        model, column = self.table.model(), grid_columns.KEYS.index("name")
        index = next((model.index(r, column) for r in range(model.rowCount())
                      if model.index(r, column).data()), None)
        self.assertIsNotNone(index, "no row of %d has a name to draw - not a test"
                             % model.rowCount())
        plain = QtWidgets.QStyledItemDelegate(self.table)
        self.addCleanup(plain.deleteLater)
        return index, self.table.itemDelegate(), plain

    def test_every_row_text_starts_where_it_is_drawn(self):
        index, delegate, plain = self._name_cell()
        margin = self.table.style().pixelMetric(
            QtWidgets.QStyle.PixelMetric.PM_FocusFrameHMargin, None, self.table) + 1
        shift = delegate.text_shift(self.table)
        cell = amazetheme.drawn_node("L01", "cell", "name")
        self.assertEqual(self.px(cell[1] - self.column["name"][1]), margin + shift)
        self.assertEqual(shift, self._ink_left(self._render(delegate, index))
                         - self._ink_left(self._render(plain, index)),
                         "the text is not drawn where the shift puts it")

    def test_the_selection_band_still_covers_the_whole_cell(self):
        index, delegate, plain = self._name_cell()
        ours = self._render(delegate, index, selected=True)
        theirs = self._render(plain, index, selected=True)
        self.assertNotEqual("#ff00ff", theirs.pixelColor(0, 1).name(),
                            "the style paints no band here - not a test")
        for x in range(delegate.text_shift(self.table) + 2):
            for y in (1, ours.height() - 2):
                with self.subTest(x=x, y=y):
                    self.assertEqual(theirs.pixelColor(x, y).name(),
                                     ours.pixelColor(x, y).name())

    def test_the_header_is_its_drawn_height(self):
        height = self.px(self.column["name"][4])
        self.assertEqual((height, height),
                         (self.header.minimumHeight(), self.header.maximumHeight()))

    def test_every_heading_starts_where_it_is_drawn(self):
        style = self.header.style()
        for key, node in self.column.items():
            column = grid_columns.KEYS.index(key)
            x = self.header.sectionPosition(column)
            option = QtWidgets.QStyleOptionHeader()
            option.initFrom(self.header)
            option.rect = QtCore.QRect(x, 0, self.px(node[3]), self.px(node[4]))
            option.section = column
            option.text = grid_columns.LABELS[column]
            label = style.subElementRect(
                QtWidgets.QStyle.SubElement.SE_HeaderLabel, option, self.header)
            with self.subTest(column=key):
                self.assertEqual(self.px(self.heading[key][1] - node[1]), label.x() - x)

    def test_every_shown_column_starts_at_its_drawn_width(self):
        shown = [c for c in range(len(grid_columns.KEYS))
                 if not self.table.isColumnHidden(c)]
        self.assertGreater(len(shown), 2, "too few columns shown to be a test")
        for key, node in self.column.items():
            column = grid_columns.KEYS.index(key)
            with self.subTest(column=key):
                self.assertEqual(node[3], self.panel.COLUMN_DEFAULT_WIDTH[key])
                if column in shown[:-1]:    # the last shown column takes the slack
                    self.assertEqual(self.px(node[3]), self.table.columnWidth(column))

    def test_every_tick_box_is_where_it_is_drawn(self):
        rows = amazetheme.drawn_nodes("L01", "row")
        ticks = amazetheme.drawn_nodes("L01", "tick box")
        self.assertTrue(ticks, "L01 draws no tick - not a test")
        for node in ticks:
            key = amazetheme.drawn_name(node)[1]
            column = self.column[key]
            row = next(r for r in rows if r[2] <= node[2] < r[2] + r[4])
            delegate = self.table.itemDelegateForColumn(grid_columns.KEYS.index(key))
            box = delegate._box(QtCore.QRect(*(self.px(v) for v in (
                column[1], row[2], column[3], row[4]))))
            with self.subTest(tick=key, y=node[2]):
                self.assertEqual(tuple(self.px(v) for v in node[1:5]),
                                 (box.x(), box.y(), box.width(), box.height()))


if __name__ == "__main__":
    unittest.main()
