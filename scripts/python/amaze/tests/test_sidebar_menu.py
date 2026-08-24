"""The Sidebar's MENU pins - `Section.SIDEBAR_MENU` through the same `panel/grid.py` builder as `GRID_MENU`; the shapes were RECORDED from the three panel.py handlers they replaced before those were deleted, so a rendering difference is a regression against shipped behaviour, not a style call."""

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
            ["Add Location", "Remove", "Locate",
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


if __name__ == "__main__":
    unittest.main()
