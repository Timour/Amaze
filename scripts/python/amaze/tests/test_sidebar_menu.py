"""The Sidebar's MENU pins - `Section.SIDEBAR_MENU` through the same `panel/grid.py` builder as `GRID_MENU`; the shapes were RECORDED from the three panel.py handlers they replaced before those were deleted, so a rendering difference is a regression against shipped behaviour, not a style call."""

import json
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import category  # noqa: E402
from amaze.panel import sections  # noqa: E402
from amaze.tests import test_support  # noqa: E402

SIDEBAR_CONTEXTS = ("MaterialSection", "CopSection", "CodeSection",    # every context with a sidebar menu
                    "FileSection", "GradientSection")


def render(menu) -> list:
    """Label, tick state, submenu children inline, "(off)" when greyed - the shape the before/after recording used."""
    out = []
    for action in menu.actions():
        if action.isSeparator():
            out.append("----")
            continue
        text = action.text()
        if action.menu() is not None:
            text += " > [%s]" % ", ".join(
                child.text() + ("" if child.isEnabled() else "(off)")
                for child in action.menu().actions())
        if action.isCheckable():
            text += "[x]" if action.isChecked() else "[ ]"
        if not action.isEnabled():
            text += "(off)"
        out.append(text)
    return out


class TheTableIsWellFormED(unittest.TestCase):
    """No panel, no Qt - every name in a row must resolve."""

    def test_every_context_has_a_sidebar_table(self):
        for name in SIDEBAR_CONTEXTS:
            with self.subTest(context=name):
                self.assertTrue(
                    getattr(sections, name).SIDEBAR_MENU,
                    "%s has a sidebar and no menu for it" % name)

    def test_every_named_verb_and_fact_resolves(self):
        for name in SIDEBAR_CONTEXTS:
            context = getattr(sections, name)
            for entry in context.SIDEBAR_MENU:
                if not entry.label:
                    continue
                with self.subTest(context=name, entry=entry.label):
                    self.assertTrue(
                        callable(getattr(context, entry.verb, None)),
                        '%s\'s "%s" names verb %r, which it does not have'
                        % (name, entry.label, entry.verb))
                    facts = [entry.shown, entry.children, entry.checkable]
                    if entry.needs not in ("any", "one", "always"):
                        facts.append(entry.needs)
                    for fact in [f for f in facts if f]:
                        self.assertTrue(
                            hasattr(context, fact),
                            "%s's %r names %r, which it does not have"
                            % (name, entry.label, fact))

    def test_the_three_asset_sections_share_ONE_table(self):
        """Not three equal copies - the same OBJECT; a copy is a copy that will drift."""
        tables = {id(getattr(sections, name).SIDEBAR_MENU)
                  for name in ("MaterialSection", "CopSection",
                               "CodeSection")}
        self.assertEqual(
            1, len(tables),
            "Material, Node and Code no longer share one sidebar table")

    def test_only_FILE_uses_a_checkable_entry(self):
        """The two per-location toggles are the only ticks in any menu - a section growing one decides its law rather than copying it."""
        for name in SIDEBAR_CONTEXTS:
            ticks = [e.label for e in getattr(sections, name).SIDEBAR_MENU
                     if e.checkable]
            with self.subTest(context=name):
                if name == "FileSection":
                    self.assertEqual(
                        ["Show Subfolders", "Show All Files"], ticks)
                else:
                    self.assertEqual([], ticks)


class NoSidebarMenuIsWrittenInThePanel(unittest.TestCase):

    def test_the_three_handlers_are_gone(self):
        import ast
        package = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(package, "panel", "panel.py"),
                  encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        offenders = [n.name for n in ast.walk(tree)
                     if isinstance(n, ast.FunctionDef)
                     and n.name.endswith("_catlist_menu")
                     and n.name != "catlist_rc_menu"]
        self.assertEqual(
            [], offenders,
            "panel.py builds a sidebar menu itself, in %s" % offenders)


class TheSidebarMenusAreWhatSHIPPED(unittest.TestCase):
    """Recorded from the three handlers before they were deleted."""

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
            panel._section().catlist_menu()
        return seen

    SPINE = ["Add Category", "Rename", "Remove", "----",
             "Sort by name", "----",
             "Set Color", "Clear Color", "----", "Export Category"]

    def test_the_three_asset_sidebars_render_the_same_spine(self):
        for key in ("material", "cop", "code"):
            with self.subTest(section=key):
                self.assertEqual(self.SPINE, self._show(key))

    def test_asset_rename_greys_on_two_rows(self):
        """Renaming acts on ONE category; Remove and the colours act on the whole selection - the Grid's selection law, unchanged."""
        shown = self._show("material", (0, 1))
        self.assertEqual(
            ["Add Category", "Rename(off)", "Remove", "----",
             "Sort by name", "----",
             "Set Color", "Clear Color", "----", "Export Category(off)"],
            shown)

    def test_color_offers_only_add_on_the_All_row(self):
        """Everything below All is a real user category; All is a view, so the per-category entries do not exist on it - Export stays, exporting from All being the whole section."""
        self.assertEqual(
            ["Add Category", "----", "Sort by name", "----",
             "Export Category"],
            self._show("gradient", (0,)))

    def test_color_offers_the_whole_spine_on_a_category(self):
        self.assertEqual(self.SPINE, self._show("gradient", (1,)))

    def test_file_on_a_real_location(self):
        shown = self._show("file", (1,))
        self.assertEqual(
            ["Add Location", "Remove", "Locate", "Label > [Add, Remove(off)]",
             "----", "Show Subfolders[ ]", "Show All Files[x]", "----",
             "Set Color", "Clear Color"],
            shown)

    def test_file_on_the_All_row(self):
        """The per-location entries grey; Show All Files stays live, because on All the tick IS the global preference."""
        shown = self._show("file", (0,))
        self.assertEqual(
            ["Add Location", "Remove(off)", "Locate(off)",
             "Label > [Add, Remove(off)](off)", "----",
             "Show Subfolders[ ](off)", "Show All Files[x]", "----",
             "Set Color(off)", "Clear Color(off)"],
            shown)

    def test_file_label_submenu_greys_remove(self):
        """Remove GREYS in the Label submenu, never vanishes - an entry that vanishes moves the row under the cursor between two right-clicks."""
        for rows in ((0,), (1,)):
            with self.subTest(row=rows[0]):
                label = [row for row in self._show("file", rows)
                         if row.startswith("Label")]
                self.assertEqual(1, len(label))
                self.assertIn(
                    "Remove(off)", label[0],
                    "Remove left the Label submenu instead of greying: %s"
                    % label[0])

    def test_file_show_all_reflects_the_preference(self):
        """A tick that does not read its own state is a switch showing the wrong position - and this one is per location."""
        panel = self.panel
        before = bool(panel.prefs.file_show_unknown)
        shown = self._show("file", (0,))
        tick = [r for r in shown if r.startswith("Show All Files")][0]
        self.assertEqual(
            before, "[x]" in tick,
            "Show All Files shows %r while the preference is %r"
            % (tick, before))

    def test_a_menu_never_starts_or_ends_on_a_divider(self):
        for key, rows in (("material", (0,)), ("gradient", (0,)),
                          ("gradient", (1,)), ("file", (0,)),
                          ("file", (1,)), ("code", (0,))):
            with self.subTest(section=key, row=rows[0]):
                shown = self._show(key, rows)
                if not shown:
                    continue
                self.assertNotEqual("----", shown[0])
                self.assertNotEqual("----", shown[-1])
                self.assertNotIn(
                    ["----", "----"],
                    [shown[i:i + 2] for i in range(len(shown) - 1)])


class ADismissedSidebarMenuRunsNOTHING(unittest.TestCase):
    """Dismissal fires no verb - dispatch is a dict, so the None-collision the old handlers guarded by hand cannot come back."""

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
                context = panel._section()
                called = []
                verbs = {e.verb for e in context.SIDEBAR_MENU if e.verb}
                patches = [
                    mock.patch.object(
                        type(context), verb,
                        lambda *a, _v=verb, **k: called.append(_v))
                    for verb in verbs]
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


class StructuralSignalsStayOutsideRelayout(unittest.TestCase):
    """`ui_helpers.relayout` is for DATA changes only: a layout-change pair around begin/endInsert/RemoveRows hands attached proxies dangling persistent indexes at the closing signal - a native H21 segfault (research.md, 2026-08-04)."""

    def test_no_relayout_wraps_a_categories_row_signal(self):
        import ast

        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "panel", "sections.py")
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        offenders = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.With) and node.items):
                continue
            context = node.items[0].context_expr
            if "relayout" not in ast.dump(context):
                continue
            for call in ast.walk(node):
                if not (isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr in ("check_add_category",
                                               "remove_category")):
                    continue
                receiver = call.func.value
                if (isinstance(receiver, ast.Attribute)
                        and receiver.attr == "categories"):
                    offenders.append(
                        "sections.py:%d %s inside relayout"
                        % (call.lineno, call.func.attr))
        self.assertEqual(
            [], offenders,
            "a categories-model row signal is paired with a layout "
            "change - the H21 segfault shape the relayout docstring "
            "bans: %s" % offenders)

    ROW_WRITERS = (    # each inserts or removes rows, or saves - and a save adopts a peer's rows
        "save", "add_asset", "import_record", "update_asset",
        "update_asset_content", "convert_karma_to_redshift",
        "convert_redshift_to_karma", "check_add_category", "remove_asset",
        "removeRow", "removeRows", "insertRow", "insertRows")
    CATEGORY_WRITERS = ("remove_category", "rename_category")    # move rows or save on a CATEGORIES model

    def test_no_relayout_wraps_a_row_move_or_a_save(self):
        """Both files that open the pair, every verb that can move rows under it."""
        import ast

        package = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        offenders = []
        for name in ("panel.py", "sections.py"):
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
                    verb = call.func.attr
                    receiver = ast.unparse(call.func.value)
                    if verb in self.ROW_WRITERS or (
                            verb in self.CATEGORY_WRITERS
                            and "cat" in receiver.lower()):
                        offenders.append("%s:%d %s.%s" % (
                            name, call.lineno, receiver, verb))
        self.assertEqual(
            [], offenders,
            "a call that can insert, remove or save runs inside a "
            "layout-change pair - the H21 segfault shape: %s" % offenders)


class TheCategoryVerbsMoveNoRowInsideALayoutChange(unittest.TestCase):
    """Rename and Remove edit asset rows in place; the save that follows adopts a peer's rows."""

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
        document["assets"].append({"id": "PEER-CAT", "categories": [],
                                   "name": "Filed elsewhere", "tags": []})
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=4)

    def _row(self, stored):
        proxy = self.panel.cat_list.model()
        role = proxy.sourceModel().CatSortRole
        for row in range(proxy.rowCount()):
            if proxy.index(row, 0).data(role) == stored:
                return proxy.index(row, 0)
        self.fail("premise: no sidebar row is stored %r" % stored)

    def _assert_no_row_moved_inside(self, caught, verb):
        self.assertIn("Filed elsewhere",
                      [asset.name for asset in self.model.assets],
                      "premise: the save adopted nothing")
        self.assertEqual(
            [], caught,
            "%s moved rows inside a layout-change pair - the shape that "
            "segfaults H21: %s" % (verb, caught))

    def test_rename(self):
        self.assertTrue(self.panel._stand_on_category("usds"))
        index = self._row("usds")
        with mock.patch.object(self.panel, "ask_category_name",
                               lambda _title, _default="": "Surfaces"), \
                test_support.row_moves_inside_a_layout_change(
                    self.model, self.panel.category_model) as caught:
            self.section.menu_rename_category([index], index)
        self._assert_no_row_moved_inside(caught, "Rename")
        self.assertEqual("Surfaces", self.panel._selected_category_name(),
                         "the renamed row is no longer where you stand")
        self.assertEqual(
            "Surfaces", self.panel.material_sorted_model.filter_value(
                self.model.CategoryRole),
            "the grid is still narrowed to the old name")
        self.assertEqual(
            4, self._row("Surfaces").data(category.SIDEBAR_COUNT_ROLE),
            "the renamed row counts from a stale cache")

    def test_rename_opens_on_the_name_being_renamed(self):
        from amaze.dialogs import base_dialog
        self.assertTrue(self.panel._stand_on_category("usds"))
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
                self.panel.category_model.CatSortRole)
            for row in range(self.panel.category_model.rowCount())])


class ANameThatReadsAsAnotherIsThatCategory(unittest.TestCase):
    """`_WIP` reads WIP, so a typed WIP names it: Add and Rename never leave two rows reading alike."""

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
        role = proxy.sourceModel().CatSortRole
        found = [proxy.index(row, 0) for row in range(proxy.rowCount())
                 if proxy.index(row, 0).data(role) == stored]
        self.assertTrue(found, "premise: no sidebar row is stored %r" % stored)
        return found[0]

    def _renamed(self, stored, typed):
        filed = [asset for asset in self.panel.material_model.assets
                 if stored in asset.categories]
        self.assertTrue(filed, "premise: nothing is filed under %r" % stored)
        self.assertTrue(self.panel._stand_on_category(stored), "premise: no row to stand on")
        index = self._sidebar_row(stored)
        with self._typing(typed):
            self.section.menu_rename_category([index], index)
        return filed

    def test_adding_WIP_adds_no_second_row_reading_WIP(self):
        with self._typing("WIP"):
            self.section.menu_add_category([], None)
        self.assertEqual(1, self._rows_read().count("WIP"),
                         "Add Category made a second row reading WIP")

    def test_renaming_to_WIP_files_into_the_row_reading_WIP(self):
        filed = self._renamed("usds", "WIP")
        self.assertEqual(1, self._rows_read().count("WIP"),
                         "Rename made a second row reading WIP")
        self.assertEqual([["_WIP"]] * len(filed),
                         [list(asset.categories) for asset in filed],
                         "the renamed tiles are not under the row reading WIP")
        self.assertEqual("_WIP", self.panel._selected_category_name(),
                         "the sidebar left the row the renamed tiles went to")
        self.assertEqual("_WIP", self.panel.material_sorted_model.filter_value(
            self.panel.material_model.CategoryRole),
            "the grid is narrowed to a category that is gone")

    def test_renaming_onto_a_row_above_merges_and_stands_there(self):
        filed = self._renamed("usds", "Karma_Mats")
        self.assertEqual(1, self._rows_read().count("Karma_Mats"),
                         "renaming onto a category that exists left two rows")
        self.assertEqual([["Karma_Mats"]] * len(filed),
                         [list(asset.categories) for asset in filed])
        self.assertEqual("Karma_Mats", self.panel._selected_category_name(),
                         "the sidebar slid onto the row below the merged one")

    def test_renaming_to_All_changes_nothing(self):
        before = self._rows_read()
        self._renamed("usds", "All")
        self.assertEqual(before, self._rows_read(),
                         "a category was renamed onto the All row")


if __name__ == "__main__":
    unittest.main()
