"""Sidebar menu tests: `Section.SIDEBAR_MENU` goes through the same builder as `GRID_MENU`."""

import json
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.actions import nodes as node_actions  # noqa: E402
from amaze.core import category, file_library, locations  # noqa: E402
from amaze.helpers import helpers  # noqa: E402
from amaze.panel import sections  # noqa: E402
from amaze.tests import test_support  # noqa: E402

SIDEBAR_CONTEXTS = ("MaterialSection", "CopSection", "CodeSection",    # every context with a sidebar menu
                    "FileSection", "GradientSection")


def _row(action) -> str:
    """One row: "----" for a divider, else its label, tick state and "(off)" when greyed."""
    if action.isSeparator():
        return "----"
    text = action.text()
    if action.menu() is not None:
        text += " > [%s]" % ", ".join(_row(child) for child in action.menu().actions())
    if action.isCheckable():
        text += "[x]" if action.isChecked() else "[ ]"
    if not action.isEnabled():
        text += "(off)"
    return text


def render(menu) -> list:
    """Every row of a menu, its submenus inline - the format the before/after recording used."""
    return [_row(action) for action in menu.actions()]


LABEL = "Label > [Red, Yellow, Blue, Green, ----, Custom, Remove]"    # the colour submenu
SHOW_NEW = ("Show > [Pathname[ ], Subfolder[ ], ----, Other Files[x], ----, "
            "Images[x], Geometry[x], HIP[x]]")    # a newly added location: every kind on


class TheTableIsWellFormED(unittest.TestCase):
    """No panel, no Qt - every name in a row must resolve."""

    def test_every_named_handler_and_fact_resolves(self):
        for name in SIDEBAR_CONTEXTS:
            context = getattr(sections, name)
            for entry in context.SIDEBAR_MENU:
                if not entry.label:
                    continue
                with self.subTest(context=name, entry=entry.label):
                    self.assertTrue(
                        callable(getattr(context, entry.handler, None)),
                        '%s\'s "%s" names handler %r, which it does not have'
                        % (name, entry.label, entry.handler))
                    facts = [entry.shown, entry.children, entry.checkable]
                    if entry.needs not in ("any", "one", "always"):
                        facts.append(entry.needs)
                    for fact in [f for f in facts if f]:
                        self.assertTrue(
                            hasattr(context, fact),
                            "%s's %r names %r, which it does not have"
                            % (name, entry.label, fact))


class TheSidebarMenusAreWhatSHIPPED(unittest.TestCase):
    """Each sidebar menu keeps its shipped rows; any difference is a regression, not a choice."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _show(self, key, rows=(0,)):
        panel = self.panel
        panel.section_tabs.setChecked(key)
        QtWidgets.QApplication.processEvents()
        model = panel.cat_list.model()
        self.assertIsNotNone(model, "the %s sidebar has no model" % key)
        flags = QtCore.QItemSelectionModel.SelectionFlag
        selection = panel.cat_list.selectionModel()
        selection.clearSelection()
        for position, row in enumerate(rows):
            if row >= model.rowCount():
                self.skipTest("the %s sidebar has no row %d" % (key, row))
            selection.select(
                model.index(row, 0),
                flags.ClearAndSelect if position == 0 else flags.Select)
        selection.setCurrentIndex(model.index(rows[0], 0), flags.NoUpdate)
        self.assertEqual(
            len(rows), len(selection.selectedIndexes()),
            "the helper selected %d rows, not %d"
            % (len(selection.selectedIndexes()), len(rows)))

        seen = []
        with mock.patch.object(QtWidgets.QMenu, "exec_",
                               lambda menu, *a, **k: seen.extend(
                                   render(menu))):
            panel.active_section().catlist_menu()
        return seen

    SPINE = ["Add", "Rename", "Delete", "----",
             "Sort by name", "----",
             LABEL]

    FILE_NO_LOCATION = ["Add", "Locate(off)",
                        "Rename > [Edit, ----, Set to Default(off)](off)",
                        "Remove(off)", "----", "Sort by name", "----",
                        "Show > [Pathname[ ], Subfolder[ ], ----, Other Files[ ], "
                        "----, Images[ ], Geometry[ ], HIP[ ]](off)", "----",
                        LABEL + "(off)"]

    def test_each_sidebar_renders_the_menu_that_shipped(self):
        """Rename acts on one row; All is a view, so it greys or drops the per-row entries."""
        for key, rows, prepare, expected in (
                ("material", (0,), None, self.SPINE),
                ("cop", (0,), None, self.SPINE),
                ("code", (0,), None, self.SPINE),
                ("material", (0, 1), None,
                 ["Add", "Rename(off)", "Delete", "----",
                  "Sort by name", "----",
                  LABEL]),
                ("gradient", (0,), None,
                 ["Add", "----", "Sort by name"]),
                ("gradient", (1,), None, self.SPINE),
                ("file", (0,), None, self.FILE_NO_LOCATION),
                ("file", (1,), None, self.FILE_NO_LOCATION),    # the scene row: Add only
                ("file", (2,), self._file_location,
                 ["Add", "Locate", "Rename > [Edit, ----, Set to Default(off)]",
                  "Remove", "----", "Sort by name", "----", SHOW_NEW, "----", LABEL])):
            with self.subTest(section=key, rows=rows):
                if prepare:
                    prepare()
                self.assertEqual(expected, self._show(key, rows))

    def _file_location(self):
        """The fixture's first location, with Show ticked as for a newly added location."""
        prefs = self.panel.prefs
        path = prefs.file_folders[0]
        self.addCleanup(locations.set_field, prefs, path, "kinds",
                        locations.record(prefs, path).get("kinds"))
        prefs.set_file_folder_kinds(path, locations.SHOWN_BY_DEFAULT)
        return path

    def test_file_show_reads_the_location_it_is_on(self):
        """Each Show tick reads the location's own field, or it shows the wrong state."""
        prefs = self.panel.prefs
        path = self._file_location()
        prefs.set_file_folder_kinds(path, (locations.KIND_OTHER,
                                           locations.KIND_HIP))
        self.addCleanup(prefs.set_file_folder_pathname, path, False)
        prefs.set_file_folder_pathname(path, True)
        show = [row for row in self._show("file", (2,)) if row.startswith("Show")]    # the first location
        self.assertEqual(
            ["Show > [Pathname[x], Subfolder[ ], ----, Other Files[x], ----, "
             "Images[ ], Geometry[ ], HIP[x]]"], show)


class ADismissedSidebarMenuRunsNOTHING(unittest.TestCase):
    """Dismissing the menu runs no handler: dispatch is a dict, so a None pick matches no handler."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def test_nothing_fires_when_the_menu_is_dismissed(self):
        panel = self.panel
        for key in ("material", "gradient", "file"):
            with self.subTest(section=key):
                panel.section_tabs.setChecked(key)
                QtWidgets.QApplication.processEvents()
                model = panel.cat_list.model()
                if model is None or not model.rowCount():
                    continue
                panel.cat_list.selectionModel().select(
                    model.index(0, 0),
                    QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
                context = panel.active_section()
                called = []
                handlers = {e.handler for e in context.SIDEBAR_MENU if e.handler}
                patches = [
                    mock.patch.object(
                        type(context), handler,
                        lambda *a, _v=handler, **k: called.append(_v))
                    for handler in handlers]
                with mock.patch.object(QtWidgets.QMenu, "exec_",
                                       lambda *a, **k: None):
                    for patch in patches:
                        patch.start()
                    try:
                        context.catlist_menu()
                    finally:
                        for patch in patches:
                            patch.stop()
                self.assertEqual(
                    [], called,
                    "%s ran %s after the menu was dismissed"
                    % (key, called))


class EachSubmenuRowWritesWhatItsLabelNames(unittest.TestCase):
    """Label, Show and Rename, picked through the menu's own dispatch."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)

    def _on_row(self, key, row=None):
        """Right-presses `row` of `key`'s sidebar, else the first real row; returns context, key."""
        self.panel.section_tabs.setChecked(key)
        QtWidgets.QApplication.processEvents()
        view = self.panel.cat_list
        if row is None:    # File's first location is below All and the scene row
            row = getattr(view.model(), "_offset", lambda: 1)()
        if row >= view.model().rowCount():
            self.skipTest("the %s sidebar has no row %d" % (key, row))
        self._row = row
        index = view.model().index(row, 0)
        context = self.panel.active_section()
        return context, context.sidebar_key(index)

    def _choose(self, *labels):
        """Right-presses the row `_on_row` chose, then picks `labels` down through the submenus."""
        view = self.panel.cat_list
        view.selectionModel().setCurrentIndex(    # every menu opens on its own right press
            view.model().index(self._row, 0), QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)

        def pick(menu, *_args, **_kwargs):
            for label in labels:
                action = next(a for a in menu.actions() if a.text() == label)
                menu = action.menu() or menu
            return action

        with mock.patch.object(QtWidgets.QMenu, "exec_", pick):
            self.panel.active_section().catlist_menu()

    def test_a_chip_colours_every_kind_of_row_and_Remove_clears_it(self):
        from amaze import amazetheme
        for key in ("material", "gradient", "file"):
            with self.subTest(section=key):
                context, name = self._on_row(key)
                for label, colour in amazetheme.LABEL_COLOURS:
                    self._choose("Label", label)
                    self.assertEqual(colour, context.sidebar_colour(name).lower())
                self._choose("Label", "Remove")
                self.assertEqual("", context.sidebar_colour(name))

    def test_custom_opens_the_picker(self):
        from PySide6 import QtGui
        from amaze.helpers import ui_helpers
        context, name = self._on_row("material")
        with mock.patch.object(ui_helpers, "pick_color",
                               lambda *_a: QtGui.QColor("#123456")):
            self._choose("Label", "Custom")
        self.assertEqual("#123456", context.sidebar_colour(name))

    def test_each_show_tick_writes_its_own_field(self):
        context, path = self._on_row("file")
        prefs = self.panel.prefs
        prefs.set_file_folder_kinds(path, (locations.KIND_IMAGE, locations.KIND_GEO,
                                           locations.KIND_HIP))    # Other Files off to start
        self._choose("Show", "Images")
        self._choose("Show", "Other Files")
        self.assertEqual({locations.KIND_GEO, locations.KIND_HIP,
                          locations.KIND_OTHER},
                         set(file_library.location_kinds(prefs, path)))
        self._choose("Show", "Subfolder")
        self.assertIn(path, prefs.file_recursive_folders)
        self._choose("Show", "Pathname")
        folders = self.panel.file_folders_model
        self.assertEqual(helpers.houdini_path(path, prefs.path_style),
                         folders.display_name(path))
        self._choose("Show", "Pathname")
        self.assertEqual(os.path.basename(path.rstrip("/\\")),
                         folders.display_name(path))

    def test_pathname_shows_the_path_on_a_renamed_row(self):
        """A row the user renamed shows its path once Show ▸ Pathname is ticked."""
        context, path = self._on_row("file")
        prefs = self.panel.prefs
        self.addCleanup(prefs.set_file_folder_name, path, "")
        self.addCleanup(prefs.set_file_folder_pathname, path, False)
        prefs.set_file_folder_name(path, "Renamed Location")
        row = self.panel.cat_list.model().index(self._row, 0)
        self.assertEqual("Renamed Location", row.data())
        self._choose("Show", "Pathname")
        self.assertEqual(helpers.houdini_path(path, prefs.path_style),
                         row.data(),
                         "the renamed row kept its name with Pathname ticked")

    def test_rename_opens_on_the_folder_name_and_Set_to_Default_goes_back(self):
        context, path = self._on_row("file")
        asked = []
        with mock.patch.object(self.panel, "ask_category_name",
                               lambda title, default="": (asked.append(
                                   (title, default)), "Textures")[1]):
            self._choose("Rename", "Edit")
        folder = os.path.basename(path.rstrip("/\\"))
        self.assertEqual([("Rename Location", folder)], asked)
        folders = self.panel.file_folders_model
        self.assertEqual("Textures", folders.display_name(path))
        self._choose("Rename", "Set to Default")
        self.assertEqual(folder, folders.display_name(path))


class TheChipsArePaintedWhereTheDesignDrawsThem(unittest.TestCase):
    """A chip submenu paints each chip at `amazetheme.MENU_CHIP` inside its row."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)

    def test_each_chip_fills_its_box_and_nothing_around_it(self):
        from amaze import amazetheme
        from amaze.helpers import theme
        from amaze.panel import grid
        self.panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        section = self.panel.active_section()
        index = self.panel.cat_list.model().index(1, 0)
        menu, _handlers = grid.build_menu(self.panel, section, section.SIDEBAR_MENU, [index], index)
        self.addCleanup(menu.deleteLater)
        chips = next(a.menu() for a in menu.actions() if a.text() == "Label")
        chips.ensurePolished()
        chips.resize(chips.sizeHint())
        image = chips.grab().toImage()
        dpr = image.devicePixelRatio() or 1.0
        x, y, w, h = (theme.ui_px(n) for n in amazetheme.MENU_CHIP)
        for (_name, colour), action in zip(amazetheme.LABEL_COLOURS, chips.actions()):
            row = chips.actionGeometry(action)
            middle = int((row.x() + x + w / 2) * dpr)
            top, bottom = int((row.y() + y) * dpr), int((row.y() + y + h) * dpr) - 1

            def at(px, py):
                return image.pixelColor(px, py).name()

            with self.subTest(chip=colour):
                self.assertFalse(action.icon().isNull(), "the row lost its icon column")
                self.assertEqual([colour, colour], [at(middle, top), at(middle, bottom)],
                                 "the chip does not fill its drawn box")
                self.assertNotEqual(colour, at(middle, top - 1), "the chip starts above its box")
                self.assertNotEqual(colour, at(middle, bottom + 1), "the chip runs below its box")


class StructuralSignalsStayOutsideRelayout(unittest.TestCase):
    """`ui_helpers.relayout` is for data changes only, never around row inserts or removals."""

    ROW_WRITERS = (    # each inserts or removes rows, or saves - and a save loads another session's rows
        "save", "add_asset", "import_record", "update_asset",
        "update_asset_content", "convert",
        "check_add_category", "remove_asset",
        "removeRow", "removeRows", "insertRow", "insertRows")
    CATEGORY_WRITERS = ("remove_category", "rename_category")    # move rows or save on a CATEGORIES model

    def test_no_relayout_wraps_a_row_move_or_a_save(self):
        """Every file that may open a `relayout` pair, every method that can move rows inside it."""
        import ast

        package = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        offenders = []
        for name in ("panel.py", "sections.py", "online_import.py", "package_import.py",
                     "drop_placement.py", "tile_capture.py"):
            with open(os.path.join(package, "panel", name),
                      encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            for node in ast.walk(tree):
                if not (isinstance(node, ast.With) and any(
                        "relayout" in ast.dump(item.context_expr)
                        for item in node.items)):
                    continue
                for call in (c for stmt in node.body for c in ast.walk(stmt)):
                    if not (isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Attribute)):
                        continue
                    method = call.func.attr
                    receiver = ast.unparse(call.func.value)
                    if method in self.ROW_WRITERS or (
                            method in self.CATEGORY_WRITERS
                            and "cat" in receiver.lower()):
                        offenders.append("%s:%d %s.%s" % (
                            name, call.lineno, receiver, method))
        self.assertEqual(
            [], offenders,
            "a call that can insert, remove or save runs inside a "
            "layout-change pair - the pattern that segfaults H21: %s" % offenders)


class TheCategoryHandlersMoveNoRowInsideALayoutChange(unittest.TestCase):
    """Rename and Remove edit asset rows in place; the next save loads another session's rows."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        self.model = self.panel.material_model
        self.section = self.panel.sections["material"]
        self.assertTrue(self.model.save(), "premise: the baseline save failed")
        path = os.path.join(self.panel.prefs.dir, self.model.DB_FILENAME)
        with open(path, encoding="utf-8-sig") as handle:
            document = json.load(handle)
        document["assets"]["PEER-CAT"] = {"id": "PEER-CAT", "categories": [],
                                          "name": "Filed elsewhere", "tags": []}
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=4)

    def _row(self, stored):
        proxy = self.panel.cat_list.model()
        role = category.SIDEBAR_KEY_ROLE
        for row in range(proxy.rowCount()):
            if proxy.index(row, 0).data(role) == stored:
                return proxy.index(row, 0)
        self.fail("premise: no sidebar row is stored %r" % stored)

    def _assert_no_row_moved_inside(self, caught, operation):
        self.assertIn("Filed elsewhere",
                      [asset.name for asset in self.model.assets],
                      "premise: the save loaded no other session's row")
        self.assertEqual(
            [], caught,
            "%s moved rows inside a layout-change pair - the pattern that "
            "segfaults H21: %s" % (operation, caught))

    def test_rename(self):
        self.assertTrue(self.panel._select_category("usds"))
        index = self._row("usds")
        with mock.patch.object(self.panel, "ask_category_name",
                               lambda _title, _default="": "Surfaces"), \
                test_support.row_moves_inside_a_layout_change(
                    self.model, self.panel.category_model) as caught:
            self.section.menu_rename_category([index], index)
        self._assert_no_row_moved_inside(caught, "Rename")
        self.assertEqual("Surfaces", self.panel.selected_category_name(),
                         "the renamed row is no longer the selected one")
        self.assertEqual(
            "Surfaces", self.panel.material_sorted_model.filter_value(
                self.model.CategoryRole),
            "the grid is still narrowed to the old name")
        self.assertEqual(
            4, self._row("Surfaces").data(category.SIDEBAR_COUNT_ROLE),
            "the renamed row counts from a stale cache")

    def test_rename_opens_on_the_name_being_renamed(self):
        from amaze.dialogs import base_dialog
        self.assertTrue(self.panel._select_category("usds"))
        index = self._row("usds")
        shown = []

        def _exec(dialog):
            shown.append(dialog._line_name.text())
            return 0

        with mock.patch.object(base_dialog.NameDialog, "exec", _exec):
            self.section.menu_rename_category([index], index)
        self.assertEqual(["usds"], shown,
                         "Rename Category opened on an empty field")

    def test_remove(self):
        index = self._row("usds")
        with test_support.row_moves_inside_a_layout_change(
                self.model, self.panel.category_model) as caught:
            self.section.menu_remove_category([index], index)
        self._assert_no_row_moved_inside(caught, "Remove")
        self.assertNotIn("usds", [
            self.panel.category_model.data(
                self.panel.category_model.index(row, 0),
                category.SIDEBAR_KEY_ROLE)
            for row in range(self.panel.category_model.rowCount())])


class _FourAssetSidebars:
    """Each asset section with a kept and a gone category holding a tile, and a row below."""

    SECTIONS = ("material", "cop", "code", "gradient")

    def setUp(self):
        self.panel = test_support.fixture_panel(self)

    def _file(self, key, name):
        """One asset filed under `name` in this section's own library."""
        panel = self.panel
        if key == "cop":
            net = hou.node("/obj").createNode("copnet", "probe_" + name.lower())
            self.addCleanup(net.destroy)
            kinds = hou.copNodeTypeCategory().nodeTypes()
            net.createNode(next(kind for kind in ("constant", "ramp", "noise")
                                if kind in kinds))
            self.assertTrue(node_actions.add_asset(panel.cop_model, net, name, "", False,
                                                   name=name + " one"))
        elif key == "code":
            self.assertTrue(panel.code_model.add_asset(
                "x = 1", name + " one", "Python", name, "", False))
        else:
            panel.gradient_model.add_user_gradient(
                name + " one", name, {"keys": [0.0, 0.5],
                                      "values": [[1, 0, 0], [0, 0, 1]],
                                      "bases": ["Constant"] * 2})
        panel.active_section().stack().categories.check_add_category(name)

    def _enter(self, key):
        """This section, with a kept and a removed category each holding a tile, and a row below."""
        self.panel.section_tabs.setChecked(key)
        QtWidgets.QApplication.processEvents()
        kept, gone = "Karma_Mats", "usds"
        if key != "material":
            kept, gone = "Kept", "Gone"
            for name in (kept, gone):
                self._file(key, name)
        self.panel.active_section().stack().categories.check_add_category("Below")    # where Qt moves the selection
        self.panel.refresh_sidebar_categories()
        self.assertEqual(self._row(gone) + 1, self._row("Below"), "premise: no row below")
        return kept, gone

    def _row(self, stored):
        proxy = self.panel.cat_list.model()
        key = "" if category.is_all(stored) else stored    # the key role gives "" on All
        for row in range(proxy.rowCount()):
            if proxy.index(row, 0).data(category.SIDEBAR_KEY_ROLE) == key:
                return row
        self.fail("premise: no sidebar row is stored %r" % stored)

    def _press(self, stored):
        """What a right press does: the row is selected and current, and no click handler runs."""
        view = self.panel.cat_list
        index = view.model().index(self._row(stored), 0)
        view.selectionModel().setCurrentIndex(
            index, QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        return index

    def _click_row(self, stored):
        """A left click: the press, then the sidebar's own clicked handler. Returns the tiles."""
        self._press(stored)
        self.panel.update_selected_cat()
        QtWidgets.QApplication.processEvents()
        return self._tiles()

    def _tiles(self):
        grid = self.panel.thumblist.model()
        return sorted(str(grid.index(row, 0).data()) for row in range(grid.rowCount()))

    def _assert_selected(self, stored, tiles):
        st = self.panel.active_section().stack()
        self.assertEqual(tiles, self._tiles(), "the grid does not show the selected row")
        self.assertEqual("" if category.is_all(stored) else stored,
                         st.proxy.filter_value(st.model.CategoryRole) or "",
                         "the grid is narrowed to another category")
        view = self.panel.cat_list
        row = self._row(stored)
        self.assertEqual(row, view.currentIndex().row(), "the sidebar's current row is another")
        self.assertEqual([row], [index.row() for index in view.selectedIndexes()],
                         "the sidebar highlights another row")

    def _each_section(self, case):
        for key in self.SECTIONS:
            with self.subTest(section=key):
                kept, gone = self._enter(key)
                everything = self._click_row("_All")
                kept_tiles = self._click_row(kept)
                self.assertTrue(kept_tiles, "premise: the kept category shows tiles")
                self.assertTrue(self._click_row(gone), "premise: the removed one shows tiles")
                case(kept, gone, everything, kept_tiles)


class RemovingACategoryLeavesNoTileOfIt(_FourAssetSidebars, unittest.TestCase):
    """Remove on the selected row selects All; on any other row the selection stays."""

    def _remove(self, stored):
        index = self._press(stored)
        self.panel.active_section().menu_remove_category([index], index)
        QtWidgets.QApplication.processEvents()

    def test_removing_the_selected_category_selects_all(self):
        def case(kept, gone, everything, kept_tiles):
            self._click_row(gone)
            self._remove(gone)
            self._assert_selected("_All", everything)
        self._each_section(case)

    def test_removing_another_category_keeps_the_selection(self):
        def case(kept, gone, everything, kept_tiles):
            self._click_row(kept)
            self._remove(gone)
            self._assert_selected(kept, kept_tiles)
        self._each_section(case)

    def test_removing_a_category_while_on_all_keeps_you_on_all(self):
        def case(kept, gone, everything, kept_tiles):
            self._click_row("_All")
            self._remove(gone)
            self._assert_selected("_All", everything)
        self._each_section(case)


class RenameAndSortKeepTheGridsRowSelected(_FourAssetSidebars, unittest.TestCase):
    """A right press changes only the sidebar, so Rename and Sort leave both on the grid's row."""

    def _rename(self, stored):
        index = self._press(stored)
        with mock.patch.object(self.panel, "ask_category_name",
                               lambda _title, _default="": "Renamed"):
            self.panel.active_section().menu_rename_category([index], index)
        QtWidgets.QApplication.processEvents()

    def _sort(self, stored):
        """Sort by name from a right press on `stored`, over a list the sort reorders."""
        categories = self.panel.active_section().stack().categories
        categories.check_add_category("Aaa")    # appended last, so the sort moves it
        self.panel.refresh_sidebar_categories()
        before = categories.order_snapshot()
        index = self._press(stored)
        self.panel.active_section().menu_sort_categories([index], index)
        QtWidgets.QApplication.processEvents()
        self.assertNotEqual(before, categories.order_snapshot(), "premise: no row moved")

    def test_renaming_another_category_keeps_the_selection(self):
        def case(kept, gone, everything, kept_tiles):
            self._click_row(kept)
            self._rename(gone)
            self._assert_selected(kept, kept_tiles)
        self._each_section(case)

    def test_renaming_a_category_while_on_all_keeps_you_on_all(self):
        def case(kept, gone, everything, kept_tiles):
            self._click_row("_All")
            self._rename(gone)
            self._assert_selected("_All", everything)
        self._each_section(case)

    def test_renaming_the_selected_category_selects_its_new_name(self):
        def case(kept, gone, everything, kept_tiles):
            gone_tiles = self._click_row(gone)
            self._rename(gone)
            self._assert_selected("Renamed", gone_tiles)
        self._each_section(case)

    def test_sorting_from_another_category_keeps_the_selection(self):
        def case(kept, gone, everything, kept_tiles):
            self._click_row(kept)
            self._sort(gone)
            self._assert_selected(kept, kept_tiles)
        self._each_section(case)

    def test_sorting_while_on_all_keeps_you_on_all(self):
        def case(kept, gone, everything, kept_tiles):
            self._click_row("_All")
            self._sort(gone)
            self._assert_selected("_All", everything)
        self._each_section(case)

    def test_sorting_from_the_selected_category_keeps_it_selected(self):
        def case(kept, gone, everything, kept_tiles):
            gone_tiles = self._click_row(gone)
            self._sort(gone)
            self._assert_selected(gone, gone_tiles)
        self._each_section(case)


class ADismissedMenuRestoresTheGridsRow(_FourAssetSidebars, unittest.TestCase):
    """A right press changes only the sidebar, so a menu closed with no pick restores it."""

    def test_the_highlight_returns_to_the_grids_row(self):
        def case(kept, gone, everything, kept_tiles):
            self._click_row(kept)
            self._press(gone)
            with mock.patch.object(QtWidgets.QMenu, "exec_", lambda *a, **k: None):
                self.panel.active_section().catlist_menu()
            QtWidgets.QApplication.processEvents()
            self._assert_selected(kept, kept_tiles)
        self._each_section(case)


class ANameThatReadsAsAnotherIsThatCategory(unittest.TestCase):
    """`_WIP` shows as WIP, so typed WIP means it: Add and Rename never make two rows alike."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        self.section = self.panel.sections["material"]
        self.categories = self.panel.category_model
        self.categories.check_add_category("_WIP")

    def _rows_read(self):
        return [self.categories.data(self.categories.index(row, 0))
                for row in range(self.categories.rowCount())]

    def _typing(self, name):
        return mock.patch.object(self.panel, "ask_category_name",
                                 lambda _title, _default="": name)

    def _sidebar_row(self, stored):
        proxy = self.panel.cat_list.model()
        role = category.SIDEBAR_KEY_ROLE
        found =[proxy.index(row, 0) for row in range(proxy.rowCount())
                 if proxy.index(row, 0).data(role) == stored]
        self.assertTrue(found, "premise: no sidebar row is stored %r" % stored)
        return found[0]

    def _renamed(self, stored, typed):
        filed = [asset for asset in self.panel.material_model.assets
                 if stored in asset.categories]
        self.assertTrue(filed, "premise: nothing is filed under %r" % stored)
        self.assertTrue(self.panel._select_category(stored), "premise: no row to select")
        index = self._sidebar_row(stored)
        with self._typing(typed):
            self.section.menu_rename_category([index], index)
        return filed

    def test_adding_WIP_adds_no_second_row_reading_WIP(self):
        with self._typing("WIP"):
            self.section.menu_add_category([], None)
        self.assertEqual(1, self._rows_read().count("WIP"),
                         "Add made a second row reading WIP")

    def test_renaming_to_WIP_files_into_the_row_reading_WIP(self):
        filed = self._renamed("usds", "WIP")
        self.assertEqual(1, self._rows_read().count("WIP"),
                         "Rename made a second row reading WIP")
        self.assertEqual([["_WIP"]] * len(filed),
                         [list(asset.categories) for asset in filed],
                         "the renamed tiles are not under the row reading WIP")
        self.assertEqual("_WIP", self.panel.selected_category_name(),
                         "the sidebar does not select the row the renamed tiles moved to")
        self.assertEqual("_WIP", self.panel.material_sorted_model.filter_value(
            self.panel.material_model.CategoryRole),
            "the grid is narrowed to a category that is gone")

    def test_renaming_onto_a_row_above_merges_and_selects_it(self):
        filed = self._renamed("usds", "Karma_Mats")
        self.assertEqual(1, self._rows_read().count("Karma_Mats"),
                         "renaming onto a category that exists left two rows")
        self.assertEqual([["Karma_Mats"]] * len(filed),
                         [list(asset.categories) for asset in filed])
        self.assertEqual("Karma_Mats", self.panel.selected_category_name(),
                         "the sidebar selected the row below the merged one")

    def test_renaming_to_All_changes_nothing(self):
        before = self._rows_read()
        self._renamed("usds", "All")
        self.assertEqual(before, self._rows_read(),
                         "a category was renamed onto the All row")


if __name__ == "__main__":
    unittest.main()
