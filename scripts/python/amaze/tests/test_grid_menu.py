"""The Grid area's MENU: one builder over a per-section entry table - the table says what the UI text register says, and the builder turns it into exactly the menu that shipped. THE PINNED MENUS BELOW ARE RECORDED OUTPUT of the six handlers this replaced, captured at 723a574 before a line was moved, not a transcription of intent - do not correct one to match a reading of the code. The single deliberate difference is the empty selection: the menu always opens and entries needing a selection grey out."""

import ast
import contextlib
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

from amaze.core import file_library, locations, renderers  # noqa: E402
from amaze.helpers import ui_helpers  # noqa: E402
from amaze.panel import grid, sections  # noqa: E402
from amaze.render.material_conversion import engine as conversion_engine  # noqa: E402
from amaze.tests import test_support  # noqa: E402

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
plugins_loaded = test_support.plugins_loaded


def off_unless_loaded(renderer) -> str:
    """The marker a child shows on THIS host: greyed where the plugin is not loaded."""
    return "" if conversion_engine.api(renderer).available() else "(off)"

MENU_CONTEXTS = ("MaterialSection", "GradientSection", "CopSection",  # every context that offers a grid menu, by class name
                 "CodeSection", "FileSection", "OnlineContext")


def render(menu) -> list:
    """One string per row: the label, an off marker when greyed, and a submenu's children inline - the same shape the recorder used against the six handlers, so the two are comparable."""
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
        if not action.isEnabled():
            text += "(off)"
        out.append(text)
    return out


class TheTableIsWellFormED(unittest.TestCase):
    """Reads the tables themselves - no panel, no Qt: every name in a row has to resolve on the class that declares it, because a misspelled name in a menu is invisible until somebody right-clicks that one section in Houdini (the old menus needed a REGEX test over panel.py for exactly that)."""

    def test_every_context_that_shows_tiles_has_a_table(self):
        for name in MENU_CONTEXTS:
            with self.subTest(context=name):
                self.assertTrue(
                    getattr(sections, name).GRID_MENU,
                    "%s shows tiles and offers no right-click menu"
                    % name)

    def test_every_named_verb_exists_on_the_context(self):
        for name in MENU_CONTEXTS:
            context = getattr(sections, name)
            for entry in context.GRID_MENU:
                if not entry.label:
                    continue
                with self.subTest(context=name, entry=entry.label):
                    self.assertTrue(
                        callable(getattr(context, entry.verb, None)),
                        '%s\'s "%s" names verb %r, which it does not '
                        "have - the entry would raise on click"
                        % (name, entry.label, entry.verb))

    def test_every_named_FACT_exists_on_the_context(self):
        """A name that resolves to nothing reads as False, so a missing `shown` silently deletes the entry and a missing `needs` silently greys it forever - both look like a design decision."""
        for name in MENU_CONTEXTS:
            context = getattr(sections, name)
            for entry in context.GRID_MENU:
                if not entry.label:
                    continue
                names = [entry.shown, entry.children]
                if entry.needs not in ("any", "one", "always"):
                    names.append(entry.needs)
                for fact in [n for n in names if n]:
                    with self.subTest(context=name, fact=fact):
                        self.assertTrue(
                            hasattr(context, fact),
                            "%s's %r table names %r, which it does not "
                            "have" % (name, entry.label, fact))

    def test_a_submenu_row_declares_a_verb_to_carry_its_payload(self):
        """A submenu's children all dispatch through the PARENT's verb with the child's payload - a parent with children and no verb builds rows that do nothing."""
        for name in MENU_CONTEXTS:
            context = getattr(sections, name)
            for entry in context.GRID_MENU:
                if entry.children:
                    with self.subTest(context=name, entry=entry.label):
                        self.assertTrue(
                            entry.verb,
                            '%s\'s "%s" submenu has no verb, so picking '
                            "a row in it does nothing" % (name, entry.label))


class NoMenuIsWrittenInThePanelAnyMore(unittest.TestCase):
    """The source half: the six handlers are gone, and a seventh must not grow back beside the table - a menu written in panel.py is a menu nothing in this file can see."""

    def _panel_tree(self):
        with open(os.path.join(PACKAGE, "panel", "panel.py"),
                  encoding="utf-8") as handle:
            return ast.parse(handle.read())

    MAY_BUILD_A_MENU = {  # the menus panel.py may still build - NAMED, not counted: a count says one too many without saying which, and deleting a hand menu has to come back here and delete its line
        "init_ui",                      # the toolbar's Filter menu
        "_material_lop_viewport_drop",  # the Drag & Drop Engine's
        "_build_menus",                 # the online eye's kind filter (All/Materials/Colors/Nodes/Code) - a toolbar menu, not a grid route
    }

    def test_ONE_builder_constructs_the_GRID_menu(self):
        """A QMenu built for the grid anywhere but the builder is a second route through the area wearing the table's clothes."""
        with open(os.path.join(PACKAGE, "panel", "grid.py"),
                  encoding="utf-8") as handle:
            self.assertIn("QtWidgets.QMenu(", handle.read(),
                          "the builder does not build a menu")
        builders = set()
        for func in ast.walk(self._panel_tree()):
            if not isinstance(func, ast.FunctionDef):
                continue
            for call in ast.walk(func):
                if (isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "QMenu"):
                    builders.add(func.name)
        self.assertEqual(
            self.MAY_BUILD_A_MENU, builders,
            "panel.py builds menus in %s - anything new here is a "
            "second route through an area that has a table"
            % sorted(builders - self.MAY_BUILD_A_MENU))


class TheBuilderTidiesItsOwnSeparators(unittest.TestCase):
    """A table with conditional rows produces leading, doubled and trailing dividers - each hand-written menu avoided all three by luck that held while nobody added an entry."""

    def test_no_leading_doubled_or_trailing_divider_survives(self):
        for rows, tidy in (([None, "b"], ["b"]),
                           (["a", None, None, "b"], ["a", None, "b"]),
                           (["a", None], ["a"]),
                           ([None, None], [])):
            with self.subTest(rows=rows):
                self.assertEqual(tidy, grid._tidy_separators(rows))


class TheMenusAreWhatSHIPPED(unittest.TestCase):
    """The recorded output of the six handlers, driven through the one builder - captured from the shipped code at 723a574, so a failure here is the rewrite changing what a person sees, not a disagreement about what it should be. The EMPTY cases are the one deliberate change and are marked where they differ."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _show(self, key, rows=()):
        """Select `rows` in section `key`, return the rendered menu."""
        panel = self.panel
        panel.section_tabs.setChecked(key)
        QtWidgets.QApplication.processEvents()
        proxy = panel.thumblist.model()
        selection = panel.thumblist.selectionModel()
        selection.clearSelection()
        flags = QtCore.QItemSelectionModel.SelectionFlag
        for position, row in enumerate(rows):
            selection.select(
                proxy.index(row, 0),
                flags.ClearAndSelect if position == 0 else flags.Select)
        if rows:
            selection.setCurrentIndex(proxy.index(rows[0], 0),  # NoUpdate: the view's own setCurrentIndex CLEARS the selection, which reduced every multi-selection here to one row and passed the one-selected menu
                                      flags.NoUpdate)
        self.assertEqual(
            len(rows), len(selection.selectedIndexes()),
            "the helper did not select %d rows, so this test is about "
            "a different selection than it says" % len(rows))

        seen = []
        with mock.patch.object(QtWidgets.QMenu, "exec_",
                               lambda menu, *a, **k: seen.extend(
                                   render(menu))):
            panel._section().rc_menu()
        return seen

    def _rows_of_kind(self, kind):
        panel = self.panel
        panel.section_tabs.setChecked("file")
        QtWidgets.QApplication.processEvents()
        proxy = panel.thumblist.model()
        role = panel.file_files_model.KindRole
        return [row for row in range(proxy.rowCount())
                if (proxy.index(row, 0).data(role) or "") == kind]

    def test_material_with_one_two_or_nothing_selected(self):
        """Every entry acts on the whole selection and stays live."""
        for rows, expected in (
                ((0,),
                 ["Copy To > [/mat, /stage/materiallibrary]",
                  "Convert to > [MaterialX(off), Redshift(off), Octane(off)](off)",    # neither renderer
                  "----",
                  "Update Render", "Capture", "Customize", "Favorite",
                  "Export Package", "Delete"]),
                ((0, 1),
                 ["Copy To > [/mat, /stage/materiallibrary]",
                  "Convert to > [MaterialX(off), Redshift, Octane]",
                  "----",
                  "Update Render", "Capture(off)", "Customize", "Favorite",    # one capture, one tile
                  "Export Package", "Delete"]),
                ((),
                 ["Copy To > [/mat, /stage/materiallibrary](off)",
                  "Convert to > [MaterialX(off), Redshift(off), Octane(off)](off)", "----",
                  "Update Render(off)", "Capture(off)", "Customize(off)",
                  "Favorite(off)", "Export Package(off)", "Delete(off)"])):
            with self.subTest(selected=len(rows)):
                with plugins_loaded("Redshift", "Octane"):
                    shown = self._show("material", rows)
                self.assertEqual(expected, shown)

    def test_color_with_one_selected(self):
        shown = self._show("gradient", (0,))
        self.assertEqual(
            ["Apply",
             "Apply as > [Constant, Linear, CatmullRom, MonotoneCubic, "
             "Bezier, BSpline, Hermite]",
             "----", "Capture", "Customize", "Favorite", "Export Package",
             "Delete"],
            [row for row in shown if not row.startswith("Copy Color")])
        swatches = [row for row in shown if row.startswith("Copy Color")]
        self.assertEqual(1, len(swatches))
        self.assertIn("#", swatches[0],
                      "the swatch rows do not carry their hex codes")

    def test_color_with_two_selected(self):
        """The per-entry actions grey; Customize, Favorite and Delete act on the whole selection like every section."""
        shown = self._show("gradient", (0, 1))
        self.assertEqual(
            ["Apply(off)", "----", "Capture(off)", "Customize", "Favorite",
             "Export Package", "Delete"],
            [row for row in shown
             if not row.startswith(("Apply as", "Copy Color"))])
        for row in shown:
            if row.startswith(("Apply as", "Copy Color")):
                self.assertTrue(row.endswith("(off)"),
                                "%r stayed live on a multi-selection" % row)

    def test_node_keeps_its_shape(self):
        """The fixture has no Node assets, so this is the empty case - exactly the one that used to produce no menu at all."""
        self.assertEqual(
            ["Load(off)", "----", "Update Render(off)", "Capture(off)",
             "Customize(off)", "Favorite(off)", "Export Package(off)",
             "Delete(off)"],
            self._show("cop"))

    def test_code_with_one_or_two_selected(self):
        for rows, expected in (
                ((0,), ["New File", "----", "Apply", "Edit", "----", "Capture",
                        "Customize", "Favorite", "Export Package", "Delete"]),
                ((0, 1), ["New File", "----", "Apply(off)", "Edit(off)", "----",
                          "Capture(off)", "Customize", "Favorite", "Export Package",
                          "Delete"])):
            with self.subTest(selected=len(rows)):
                self.assertEqual(expected, self._show("code", rows))

    def test_code_offers_NEW_FILE_over_an_empty_selection(self):
        """The one entry in any section that acts on nothing, so the one that stays live when nothing is selected."""
        shown = self._show("code")
        self.assertEqual("New File", shown[0])
        self.assertTrue(all(row.endswith("(off)") for row in shown[1:]
                            if row != "----"),
                        "something other than New File is live over an "
                        "empty selection: %s" % shown)

    def test_file_menus_follow_the_kind_and_the_count_and_never_delete(self):
        """No Delete for any kind: these are the user's own files, and an os.remove once took some."""
        for kind, count, expected in (
                (locations.KIND_IMAGE, 1,
                 ["Import", "Copy Path", "----", "Show Location",
                  "Update Render", "Capture", "Customize", "Favorite",
                  "Export Package"]),
                (locations.KIND_IMAGE, 2,    # an image loads onto ONE node parameter
                 ["Import(off)", "Copy Path", "----", "Show Location(off)",
                  "Update Render", "Capture(off)", "Customize", "Favorite",
                  "Export Package"]),
                (locations.KIND_GEO, 2,      # geometry imports the whole selection
                 ["Import", "Copy Path", "----", "Show Location(off)",
                  "Update Render", "Capture(off)", "Customize", "Favorite",
                  "Export Package"]),
                (locations.KIND_HIP, 1,      # a scene captures only while it is the open one
                 ["Load", "Copy Path", "----", "Show Location",
                  "Capture(off)", "Customize", "Favorite",
                  "Export Package"]),
                (locations.KIND_OTHER, 1,    # what Houdini cannot open is absent, not greyed
                 ["Copy Path", "----", "Show Location", "Capture", "Customize",
                  "Favorite", "Export Package"])):
            with self.subTest(kind=kind, selected=count):
                rows = self._rows_of_kind(kind)
                self.assertGreaterEqual(len(rows), count,
                                        "the fixture has too few %s rows" % kind)
                self.assertEqual(expected, self._show("file", rows[:count]))

    def test_online_menu_over_an_empty_selection(self):
        """Built directly rather than by entering the online world (that world reaches the network) - CHANGED 2026-08-03: it used to show Refresh alone, because both imports were built only `if records`; Refresh acts on nothing, so it is the one that stays live."""
        context = self.panel.online_context
        menu, _verbs = grid.build_grid_menu(self.panel, context, [], None)
        plugins = (off_unless_loaded("Redshift"), off_unless_loaded("Octane"))
        self.assertEqual(
            ["Import to Materials > [MaterialX, Redshift%s, Octane%s](off)" % plugins,
             "Import to Scene > [MaterialX, Redshift%s, Octane%s](off)" % plugins,
             "Refresh"],
            render(menu))

    def test_online_imports_say_HOW_MANY_they_are_about_to_fetch(self):
        """The count suffix, on a multi-selection only - rendered from the indexes the menu was built with, and the import runs on those same indexes; the old menu counted one read of the selection and imported from another."""
        context = self.panel.online_context
        proxy = self.panel.matx_sorted_model
        pretend = [proxy.index(row, 0) for row in range(3)]
        menu, _verbs = grid.build_grid_menu(
            self.panel, context, pretend, pretend[0])
        labels = [action.text() for action in menu.actions()]
        self.assertIn("Import to Materials (3)", labels)
        self.assertIn("Import to Scene (3)", labels)
        self.assertNotIn("Refresh (3)", labels,
                         "Refresh acts on nothing, so a count is a lie")
        one = pretend[:1]
        menu, _verbs = grid.build_grid_menu(self.panel, context, one, one[0])
        self.assertIn("Import to Materials",
                      [action.text() for action in menu.actions()],
                      "a single row carries a count")


class TheRowTheMenuIsAboutIsAlwaysSELECTED(unittest.TestCase):
    """Qt's current index and its selection move independently, so a current index OUTSIDE the selection is reachable - File's Load, Show Location and Capture Preview each read it raw, and an invalid-only fallback cannot see the case where it is valid and points at a row nobody selected."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def test_a_current_index_outside_the_selection_is_ignored(self):
        panel = self.panel
        panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        proxy = panel.thumblist.model()
        self.assertGreater(proxy.rowCount(), 2, "need three rows")
        flags = QtCore.QItemSelectionModel.SelectionFlag
        selection = panel.thumblist.selectionModel()
        selection.select(proxy.index(2, 0), flags.ClearAndSelect)
        selection.setCurrentIndex(proxy.index(0, 0), flags.NoUpdate)  # a VALID current index somewhere else entirely; the view's own setCurrentIndex would clear the selection and make the condition unreachable
        self.assertEqual(
            [2], [i.row() for i in selection.selectedIndexes()],
            "the setup did not leave the current index outside the "
            "selection, so this test cannot see the defect")

        seen = {}

        def _capture(_panel, context, entries, indexes, current):  # patches build_menu, not build_grid_menu - the open path goes through the general builder since the sidebar menus joined it, and patching the grid wrapper caught nothing
            seen["current"] = current
            seen["indexes"] = list(indexes)
            return QtWidgets.QMenu(), {}

        with mock.patch.object(grid, "build_menu", _capture), \
                mock.patch.object(QtWidgets.QMenu, "exec_",
                                  lambda *a, **k: None):
            panel._section().rc_menu()

        self.assertEqual([2], [i.row() for i in seen["indexes"]])
        self.assertEqual(
            2, seen["current"].row(),
            "the menu is about row %d, which nobody selected"
            % seen["current"].row())


class AMenuDoesNotOUTLIVEItsRightClick(unittest.TestCase):
    """A QMenu is built with the panel as its PARENT, so nothing deletes it when it closes: twenty right-clicks in Materials left FORTY QMenus alive (the menu plus its Copy To submenu, every time) for the rest of the Houdini session, in all six handlers - one builder means one `deleteLater`."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def test_twenty_right_clicks_leave_nothing_behind(self):
        panel = self.panel
        panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        proxy = panel.thumblist.model()
        panel.thumblist.selectionModel().select(
            proxy.index(0, 0),
            QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)

        def live_menus():
            return len(panel.findChildren(QtWidgets.QMenu))

        before = live_menus()
        with mock.patch.object(QtWidgets.QMenu, "exec_",
                               lambda *a, **k: None):
            for _ in range(20):
                panel._section().rc_menu()
        QtWidgets.QApplication.sendPostedEvents(  # processEvents NEVER delivers DeferredDelete (research.md - Widget teardown); without this the count is unchanged either way and the test is vacuous
            None, QtCore.QEvent.Type.DeferredDelete)

        self.assertEqual(
            before, live_menus(),
            "twenty right-clicks left %d menus parented to the panel"
            % (live_menus() - before))


class DispatchIsByIDENTITYNotByComparison(unittest.TestCase):
    """The bug family the dict retires: a dismissed menu answers None and so does a conditional entry that was never built, so equality dispatch matched None == None and ran the Redshift converter on every dismissed right-click - the guard had to be remembered per entry, while a dict lookup on None finds nothing."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def test_a_dismissed_menu_runs_NOTHING(self):
        panel = self.panel
        for key in ("material", "gradient", "code", "file"):
            with self.subTest(section=key):
                panel.section_tabs.setChecked(key)
                QtWidgets.QApplication.processEvents()
                proxy = panel.thumblist.model()
                if not proxy.rowCount():
                    continue
                panel.thumblist.selectionModel().select(
                    proxy.index(0, 0),
                    QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
                context = panel._section()
                called = []
                verbs = {entry.verb for entry in context.GRID_MENU
                         if entry.verb}
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
                        context.rc_menu()
                    finally:
                        for patch in patches:
                            patch.stop()
                self.assertEqual(
                    [], called,
                    "%s ran %s after the menu was dismissed" % (key, called))

    def _material_convert_children(self, *held):
        """Convert to's children with the selection's renderers and every plugin pinned: the TABLE."""
        panel = self.panel
        panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        context = panel._section()
        with mock.patch.object(type(context), "_sources_held",
                               lambda _self, _indexes: frozenset(held)), \
                plugins_loaded("Redshift", "Octane"):
            indexes = context.grid_selection()
            menu, _verbs = grid.build_grid_menu(
                panel, context, indexes, None)
        row = [r for r in render(menu) if r.startswith("Convert to")]
        return row[0] if row else None

    def test_convert_to_greys_the_renderer_the_selection_already_is(self):
        """Drawn as C01b: the child naming what the selection already is greys; the others are live."""
        self.assertEqual("Convert to > [MaterialX(off), Redshift, Octane]",
                         self._material_convert_children("Karma"))
        self.assertEqual("Convert to > [MaterialX, Redshift(off), Octane]",
                         self._material_convert_children("Redshift"))
        self.assertEqual("Convert to > [MaterialX, Redshift, Octane]",
                         self._material_convert_children("Karma", "Redshift"))
        self.assertEqual("Convert to > [MaterialX, Redshift, Octane(off)]",
                         self._material_convert_children("Octane"))

    def _select_karma_rows(self, count):
        """Select up to `count` Karma materials; answers the menu's own selection."""
        panel = self.panel
        panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        proxy = panel.material_sorted_model
        model = panel.material_model
        rows = [row for row in range(proxy.rowCount())
                if model.assets[proxy.mapToSource(
                    proxy.index(row, 0)).row()].renderer == "Karma"][:count]
        selection = panel.material_selection_model
        selection.clearSelection()
        for row in rows:
            selection.select(proxy.index(row, 0),
                             QtCore.QItemSelectionModel.SelectionFlag.Select)
        indexes = panel._section().grid_selection()
        self.assertEqual(len(rows), len(indexes), "premise: the rows are selected")
        self.assertTrue(indexes, "premise: the fixture has Karma materials")
        return indexes

    def test_the_parent_greys_when_no_child_is_live(self):
        """A Karma selection where neither Redshift nor Octane is loaded has nothing to become."""
        panel = self.panel
        indexes = self._select_karma_rows(1)
        with plugins_loaded():
            menu, _verbs = grid.build_grid_menu(
                panel, panel._section(), indexes, indexes[0])
        row = [r for r in render(menu) if r.startswith("Convert to")]
        self.assertEqual(["Convert to > [MaterialX(off), Redshift(off), Octane(off)](off)"], row)

    def test_convert_to_dispatches_by_the_child_picked(self):
        """One verb, the payload names the renderer: Redshift reaches the Redshift door and nothing else, Karma the Karma one."""
        panel = self.panel
        panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        context = panel._section()
        with mock.patch.object(panel, "convert_selected") as convert:
            context.menu_convert_to([], None, "Redshift")
            context.menu_convert_to([], None, "Karma")
            context.menu_convert_to([], None)
        self.assertEqual([mock.call("Redshift"), mock.call("Karma"),
                          mock.call("Karma")], convert.call_args_list)

    def test_online_import_carries_the_renderer_to_its_door(self):
        """Drawn as C06a/C06b: the child picked under either Import entry reaches the panel door as `renderer`, and a bare call (the double-click door) still means Karma."""
        panel = self.panel
        context = panel.online_context
        records = ["rec"]
        with mock.patch.object(type(context), "_records",
                               lambda self, idx: records), \
                mock.patch.object(panel, "_import_online_records") as lib, \
                mock.patch.object(panel,
                                  "_import_online_records_to_scene") as scene:
            context.menu_import_to_library([], None, "Redshift")
            lib.assert_called_once_with(records, renderer="Redshift")
            context.menu_import_to_scene([], None, "Redshift")
            scene.assert_called_once_with(records, renderer="Redshift")
            context.menu_import_to_library([], None)
            self.assertEqual({"renderer": "Karma"},
                             lib.call_args.kwargs)


def icon_image(action):
    """What a row's icon draws at 16 px: two rows wear the same icon when these match."""
    return action.icon().pixmap(QtCore.QSize(16, 16)).toImage()


class EveryRendererRowWEARSTheFilterMenusIcon(unittest.TestCase):
    """Drawn as C13, C01b, C06a and C06b: one icon per renderer, named once, drawn by one engine."""

    RENDERERS = ("MaterialX", "Redshift", "Octane")

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _everything_offered(self):
        """Every renderer offered in Preferences and loaded, Convert to asked about Karma rows."""
        panel = self.panel
        stack = contextlib.ExitStack()
        stack.callback(panel.build_filter_menu)    # runs LAST: the fixture's own offer, back
        for flag in ("renderer_redshift_enabled", "renderer_octane_enabled"):
            stack.callback(setattr, panel.prefs, flag, getattr(panel.prefs, flag))
            setattr(panel.prefs, flag, True)    # a property with no deleter: mock cannot undo it
        stack.enter_context(plugins_loaded("Redshift", "Octane"))
        stack.enter_context(mock.patch.object(
            sections.MaterialSection, "_sources_held",
            lambda _self, _indexes: frozenset({"Karma"})))
        panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        return stack

    def _build(self):
        """The Filter menu, then the material and online grid menus: (filter, material, online)."""
        panel = self.panel
        panel.build_filter_menu()
        context = panel._section()
        material_menu, _verbs = grid.build_grid_menu(
            panel, context, context.grid_selection(), None)
        online_menu, _verbs = grid.build_grid_menu(
            panel, panel.online_context, [], None)
        return panel.menu_filter, material_menu, online_menu

    @staticmethod
    def _rows(menu, name):
        """{label: action} for submenu `name` of `menu`."""
        for action in menu.actions():
            if action.text() == name and action.menu() is not None:
                return {child.text(): child for child in action.menu().actions()}
        return {}

    def test_convert_to_and_import_wear_the_filter_menus_icons(self):
        with self._everything_offered():
            filter_menu, material_menu, online_menu = self._build()
            filtered = {act.text(): act for act in filter_menu.actions()}
            for renderer in self.RENDERERS:
                self.assertFalse(filtered[renderer].icon().isNull(),
                                 "premise: C13 draws %s's icon" % renderer)
            for menu, name in ((material_menu, "Convert to"),
                               (online_menu, "Import to Materials"),
                               (online_menu, "Import to Scene")):
                rows = self._rows(menu, name)
                for renderer in self.RENDERERS:
                    with self.subTest(menu=name, renderer=renderer):
                        self.assertIn(renderer, rows, "%s lost %s" % (name, renderer))
                        self.assertFalse(rows[renderer].icon().isNull(),
                                         "%s ▸ %s has no icon" % (name, renderer))
                        self.assertEqual(
                            icon_image(filtered[renderer]),
                            icon_image(rows[renderer]),
                            "%s ▸ %s is not the Filter menu's icon" % (name, renderer))

    def test_a_renderer_switched_off_is_offered_by_no_menu(self):
        """Hidden in Preferences ▸ Show/Hide: gone from Filter, Convert to and both Imports."""
        panel = self.panel
        for hidden in renderers.ALL:
            with self.subTest(hidden=hidden.label), self._everything_offered() as stack:
                stack.callback(setattr, panel.prefs, hidden.switch,
                               getattr(panel.prefs, hidden.switch))
                setattr(panel.prefs, hidden.switch, False)
                filter_menu, material_menu, online_menu = self._build()
                self.assertNotIn(hidden.label, [act.text() for act in filter_menu.actions()])
                for menu, name in ((material_menu, "Convert to"),
                                   (online_menu, "Import to Materials"),
                                   (online_menu, "Import to Scene")):
                    rows = self._rows(menu, name)
                    self.assertTrue(rows, "premise: %s still lists the others" % name)
                    self.assertNotIn(hidden.label, rows, "%s offers a hidden renderer" % name)

    def test_one_engine_draws_them_from_one_table(self):
        """renderers.icon names the icon; ui_helpers.menu_icon draws every menu row's."""
        drawn = []
        engine = ui_helpers.menu_icon

        def spy(spec, widget=None):
            drawn.append(spec)
            return engine(spec, widget)

        with self._everything_offered(), mock.patch.object(ui_helpers, "menu_icon", spy):
            panel = self.panel
            context = panel._section()
            for build, times in (
                    (panel.build_filter_menu, 1),
                    (lambda: grid.build_grid_menu(
                        panel, context, context.grid_selection(), None), 1),
                    (lambda: grid.build_grid_menu(
                        panel, panel.online_context, [], None), 2)):
                del drawn[:]
                kept = build()
                for stored in ("Karma", "Redshift", "Octane"):
                    with self.subTest(build=build, renderer=stored):
                        self.assertEqual(times, drawn.count(renderers.icon(stored)))
                del kept
        owners = [os.path.relpath(os.path.join(root, name), PACKAGE)
                  for root, _dirs, files in os.walk(PACKAGE)
                  if os.sep + "tests" not in root
                  for name in files if name.endswith(".py")
                  and "filter_redshift" in open(os.path.join(root, name)).read()]
        self.assertEqual([os.path.join("core", "renderers.py")], owners,
                         "the renderer icon table has more than one home")


class EveryVerbREACHESItsOwner(unittest.TestCase):
    """The five verbs that already had owners, reached THROUGH them rather than copied into a table."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _pick(self, key, label):
        panel = self.panel
        panel.section_tabs.setChecked(key)
        QtWidgets.QApplication.processEvents()
        proxy = panel.thumblist.model()
        self.assertTrue(proxy.rowCount(), "the %s fixture is empty" % key)
        flags = QtCore.QItemSelectionModel.SelectionFlag
        selection = panel.thumblist.selectionModel()
        selection.select(proxy.index(0, 0), flags.ClearAndSelect)
        selection.setCurrentIndex(proxy.index(0, 0), flags.NoUpdate)

        def _exec(menu, *_a, **_k):
            for action in menu.actions():
                if action.text() == label:
                    return action
            raise AssertionError("%s has no %r entry" % (key, label))

        with mock.patch.object(QtWidgets.QMenu, "exec_", _exec):
            panel._section().rc_menu()

    def test_FAVORITE_DELETE_and_UPDATE_PREVIEW_go_through_the_panels_entry_points(self):
        for label, owner, keys in (
                ("Favorite", "grid_toggle_favourite",
                 ("material", "gradient", "code", "file")),
                ("Delete", "grid_delete", ("material", "gradient", "code")),
                ("Update Render", "grid_update_preview", ("material", "file"))):
            for key in keys:
                with self.subTest(section=key, entry=label):
                    with mock.patch.object(type(self.panel), owner) as verb:
                        self._pick(key, label)
                    self.assertTrue(verb.called)

    def test_CUSTOMIZE_reaches_the_shared_handler_in_every_section(self):
        """The typo class the old regex test guarded: the model pair was spelled out inside five menus and a wrong name there is invisible until somebody right-clicks that section - `tile_models()` on the context answers with models it actually has."""
        for key in ("material", "gradient", "code", "file"):
            with self.subTest(section=key):
                with mock.patch.object(type(self.panel),
                                       "edit_tile_icon") as verb:
                    self._pick(key, "Customize")
                self.assertTrue(verb.called)
                model, proxy, _indexes = verb.call_args[0]
                self.assertIsNotNone(model, "%s named no model" % key)
                self.assertIsNotNone(proxy, "%s named no proxy" % key)


if __name__ == "__main__":
    unittest.main()
