"""The Grid area's MENU: one builder over a per-section entry table - the table says what the UI text register says, and the builder turns it into exactly the menu that shipped. THE PINNED MENUS BELOW ARE RECORDED OUTPUT of the six handlers this replaced, captured at 723a574 before a line was moved, not a transcription of intent - do not correct one to match a reading of the code. The single deliberate difference is the empty selection: the menu always opens and entries needing a selection grey out."""

import ast
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

from amaze.core import file_library  # noqa: E402
from amaze.panel import grid, sections  # noqa: E402
from amaze.tests import test_support  # noqa: E402

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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

    def test_DELETE_is_last_and_the_presentation_group_precedes_it(self):
        """The menu law (the UI text register, set 2026-07-31): the tile's presentation, Favorite, then Delete last of all, in every grid menu - one shared tail now, so this pins the tail rather than five copies of an ordering."""
        labels = [e.label for e in sections.GRID_MENU_TAIL if e.label]
        self.assertEqual(
            ["Update Preview", "Customize", "Favorite", "Export Package",
             "Delete"], labels)

    def test_no_section_writes_its_own_copy_of_a_tail_entry(self):
        """The five copies, as a table fact - a section that spells a tail label out in its own rows has started a sixth."""
        tail = {e.label for e in sections.GRID_MENU_TAIL if e.label}
        for name in MENU_CONTEXTS:
            context = getattr(sections, name)
            head = context.GRID_MENU[:len(context.GRID_MENU)
                                     - len(sections.GRID_MENU_TAIL)]
            for entry in head:
                with self.subTest(context=name, entry=entry.label):
                    self.assertNotIn(
                        entry.label, tail,
                        "%s writes its own %r above the shared tail"
                        % (name, entry.label))


class NoMenuIsWrittenInThePanelAnyMore(unittest.TestCase):
    """The source half: the six handlers are gone, and a seventh must not grow back beside the table - a menu written in panel.py is a menu nothing in this file can see."""

    def _panel_tree(self):
        with open(os.path.join(PACKAGE, "panel", "panel.py"),
                  encoding="utf-8") as handle:
            return ast.parse(handle.read())

    def test_the_panel_has_no_grid_rc_menu_methods_left(self):
        offenders = [node.name for node in ast.walk(self._panel_tree())
                     if isinstance(node, ast.FunctionDef)
                     and node.name.endswith("_rc_menu")
                     and node.name not in ("thumblist_rc_menu",
                                           "_thumblist_rc_menu",
                                           "catlist_rc_menu")]
        self.assertEqual(
            [], offenders,
            "panel.py builds a grid menu itself, in %s - the table is "
            "the only place an entry may be declared" % offenders)

    def test_the_dispatcher_no_longer_asks_which_WORLD_it_is_in(self):
        """`_section()` answers with the online world while it shows, and that world has a table like every other context - the `_is_online()` branch here was the last place a grid path had to know."""
        source = ast.unparse(next(
            node for node in ast.walk(self._panel_tree())
            if isinstance(node, ast.FunctionDef)
            and node.name == "_thumblist_rc_menu"))
        self.assertNotIn("_is_online", source)

    MAY_BUILD_A_MENU = {  # the menus panel.py may still build - NAMED, not counted: a count says one too many without saying which, and deleting a hand menu has to come back here and delete its line
        "init_ui",                      # the toolbar's Filter menu
        "_material_lop_viewport_drop",  # the Drag & Drop Engine's
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

    def test_a_dropped_leading_group_takes_its_divider_with_it(self):
        self.assertEqual(
            ["b"], grid._tidy_separators([None, "b"]))

    def test_two_dividers_in_a_row_become_one(self):
        self.assertEqual(
            ["a", None, "b"],
            grid._tidy_separators(["a", None, None, "b"]))

    def test_a_menu_never_ends_on_a_divider(self):
        self.assertEqual(
            ["a"], grid._tidy_separators(["a", None]))

    def test_a_menu_of_nothing_but_dividers_is_empty(self):
        self.assertEqual([], grid._tidy_separators([None, None]))


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

    def test_material_with_one_selected(self):
        self.assertEqual(
            ["Info", "Copy To > [/mat, /stage]", "----",
             "Update Preview", "Customize", "Favorite", "Export Package",
             "Delete"],
            self._show("material", (0,)))

    def test_material_with_two_selected(self):
        """Info acts on one item and greys; everything else acts on the whole selection and stays live."""
        self.assertEqual(
            ["Info(off)", "Copy To > [/mat, /stage]", "----",
             "Update Preview", "Customize", "Favorite", "Export Package",
             "Delete"],
            self._show("material", (0, 1)))

    def test_material_with_nothing_selected(self):
        """CHANGED 2026-08-03: it used to open this menu with every entry but Info LIVE, over no selection at all."""
        self.assertEqual(
            ["Info(off)", "Copy To > [/mat, /stage](off)", "----",
             "Update Preview(off)", "Customize(off)", "Favorite(off)",
             "Export Package(off)", "Delete(off)"],
            self._show("material"))

    def test_color_with_one_selected(self):
        shown = self._show("gradient", (0,))
        self.assertEqual(
            ["Apply",
             "Apply as > [Constant, Linear, CatmullRom, MonotoneCubic, "
             "Bezier, BSpline, Hermite]",
             "----", "Customize", "Favorite", "Export Package", "Delete"],
            [row for row in shown if not row.startswith("Copy Color")])
        swatches = [row for row in shown if row.startswith("Copy Color")]
        self.assertEqual(1, len(swatches))
        self.assertIn("#", swatches[0],
                      "the swatch rows do not carry their hex codes")

    def test_color_with_two_selected(self):
        """The per-entry actions grey; Customize, Favorite and Delete act on the whole selection like every section."""
        shown = self._show("gradient", (0, 1))
        self.assertEqual(
            ["Apply(off)", "----", "Customize", "Favorite",
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
            ["Load(off)", "----", "Update Preview(off)", "Customize(off)",
             "Favorite(off)", "Export Package(off)", "Delete(off)"],
            self._show("cop"))

    def test_code_with_one_selected(self):
        self.assertEqual(
            ["New File", "----", "Apply", "Edit", "----",
             "Customize", "Favorite", "Export Package", "Delete"],
            self._show("code", (0,)))

    def test_code_with_two_selected(self):
        self.assertEqual(
            ["New File", "----", "Apply(off)", "Edit(off)", "----",
             "Customize", "Favorite", "Export Package", "Delete"],
            self._show("code", (0, 1)))

    def test_code_offers_NEW_FILE_over_an_empty_selection(self):
        """The one entry in any section that acts on nothing, so the one that stays live when nothing is selected."""
        shown = self._show("code")
        self.assertEqual("New File", shown[0])
        self.assertTrue(all(row.endswith("(off)") for row in shown[1:]
                            if row != "----"),
                        "something other than New File is live over an "
                        "empty selection: %s" % shown)

    def test_code_never_offers_UPDATE_PREVIEW(self):
        """Its preview is painted from the snippet's own text under a content-addressed key, so a re-render produces the identical image - the entry existed for one commit on a consistency argument and did nothing."""
        for rows in ((), (0,), (0, 1)):
            with self.subTest(selected=len(rows)):
                self.assertNotIn(
                    "Update Preview",
                    [row.replace("(off)", "")
                     for row in self._show("code", rows)])

    def test_file_image_row(self):
        rows = self._rows_of_kind(file_library.KIND_IMAGE)
        self.assertTrue(rows, "the fixture has no image rows")
        self.assertEqual(
            ["Import", "Copy Path", "----", "Show Location",
             "Update Preview", "Customize", "Favorite", "Export Package"],
            self._show("file", rows[:1]))

    def test_file_two_images_grey_IMPORT(self):
        """An image loads onto ONE node parameter."""
        rows = self._rows_of_kind(file_library.KIND_IMAGE)
        self.assertGreater(len(rows), 1, "need two image rows")
        self.assertEqual(
            ["Import(off)", "Copy Path", "----", "Show Location(off)",
             "Update Preview", "Customize", "Favorite", "Export Package"],
            self._show("file", rows[:2]))

    def test_file_two_GEOMETRY_rows_keep_IMPORT_live(self):
        """Geometry imports the whole selection - the same entry behaves differently for a different kind, which is why the rule is a named fact and not a length check."""
        rows = self._rows_of_kind(file_library.KIND_GEO)
        self.assertGreater(len(rows), 1, "need two geometry rows")
        self.assertEqual(
            ["Import", "Copy Path", "----", "Show Location(off)",
             "Update Preview", "Customize", "Favorite", "Export Package"],
            self._show("file", rows[:2]))

    def test_file_scene_row(self):
        """Capture Preview is greyed unless the viewport is showing THIS scene, and Update Preview is not offered at all: a capture is hand-framed and only a new capture replaces it."""
        rows = self._rows_of_kind(file_library.KIND_HIP)
        self.assertTrue(rows, "the fixture has no scene rows")
        self.assertEqual(
            ["Load", "Copy Path", "----", "Show Location",
             "Capture Preview(off)", "Customize", "Favorite",
             "Export Package"],
            self._show("file", rows[:1]))

    def test_file_unknown_row_offers_only_COPY_PATH(self):
        """The honest actions for a file Houdini probably cannot open - Import, Load, Capture and Update Preview are absent rather than greyed: none of them exists for this kind. Export stays: any file rides a package whole."""
        rows = self._rows_of_kind(file_library.KIND_OTHER)
        self.assertTrue(rows, "the fixture has no unknown-kind rows")
        self.assertEqual(
            ["Copy Path", "----", "Show Location", "Customize", "Favorite",
             "Export Package"],
            self._show("file", rows[:1]))

    def test_file_NEVER_offers_delete(self):
        """These are the user's own files on disk - an os.remove here once deleted real production files."""
        for kind in (file_library.KIND_IMAGE, file_library.KIND_GEO,
                     file_library.KIND_HIP, file_library.KIND_OTHER):
            rows = self._rows_of_kind(kind)
            if not rows:
                continue
            with self.subTest(kind=kind):
                self.assertNotIn(
                    "Delete",
                    [row.replace("(off)", "")
                     for row in self._show("file", rows[:1])])

    def test_online_menu_over_an_empty_selection(self):
        """Built directly rather than by entering the online world (that world reaches the network) - CHANGED 2026-08-03: it used to show Refresh alone, because both imports were built only `if records`; Refresh acts on nothing, so it is the one that stays live."""
        context = self.panel.online_context
        menu, _verbs = grid.build_grid_menu(self.panel, context, [], None)
        self.assertEqual(
            ["Import to Materials(off)", "Import to Scene(off)", "Refresh"],
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

    def test_a_SINGLE_online_row_carries_no_count(self):
        context = self.panel.online_context
        one = [self.panel.matx_sorted_model.index(0, 0)]
        menu, _verbs = grid.build_grid_menu(self.panel, context, one, one[0])
        self.assertIn("Import to Materials",
                      [action.text() for action in menu.actions()])

    def test_no_menu_offers_a_CATEGORY_submenu(self):
        """Category left the grid menus 2026-07-31 - dragging a tile onto a sidebar row does the same job with less ceremony."""
        for key in ("material", "gradient", "cop", "code", "file"):
            with self.subTest(section=key):
                self.assertNotIn(
                    "Category",
                    [row.split(" > ")[0].replace("(off)", "")
                     for row in self._show(key, (0,) if key != "cop" else ())])

    def test_INFO_left_the_color_and_node_menus(self):
        """It left 2026-08-01; Material alone keeps it."""
        for key, rows in (("gradient", (0,)), ("cop", ())):
            with self.subTest(section=key):
                self.assertNotIn(
                    "Info", [row.replace("(off)", "")
                             for row in self._show(key, rows)])

    def test_a_menu_never_starts_or_ends_on_a_divider(self):
        """The invariant the builder owns, checked on the real menus rather than only on the helper - File over an unknown row drops four entries and its divider is the first thing left."""
        for key, rows in (("material", ()), ("material", (0,)),
                          ("gradient", ()), ("cop", ()),
                          ("code", ()), ("code", (0,)),
                          ("file", ())):
            with self.subTest(section=key, selected=len(rows)):
                shown = self._show(key, rows)
                if not shown:
                    continue
                self.assertNotEqual("----", shown[0])
                self.assertNotEqual("----", shown[-1])
                self.assertNotIn(["----", "----"],
                                 [shown[i:i + 2]
                                  for i in range(len(shown) - 1)])


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

    def test_an_entry_that_was_never_built_cannot_be_picked(self):
        """Convert to Karma with no Redshift material selected: the entry does not exist, and dismissing must not reach its verb."""
        panel = self.panel
        panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        context = panel._section()
        with mock.patch.object(type(context), "selection_has_redshift",
                               lambda *a, **k: False):
            indexes = context.grid_selection()
            menu, verbs = grid.build_grid_menu(panel, context, indexes, None)
        self.assertNotIn(
            "Convert to Karma", [a.text() for a in menu.actions()])
        self.assertNotIn(
            "menu_convert_to_karma", [verb for verb, _payload in
                                      verbs.values()])


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

    def test_FAVORITE_goes_through_the_panels_one_entry_point(self):
        for key in ("material", "gradient", "code", "file"):
            with self.subTest(section=key):
                with mock.patch.object(type(self.panel),
                                       "grid_toggle_favourite") as verb:
                    self._pick(key, "Favorite")
                self.assertTrue(verb.called)

    def test_DELETE_goes_through_the_panels_one_entry_point(self):
        for key in ("material", "gradient", "code"):
            with self.subTest(section=key):
                with mock.patch.object(type(self.panel),
                                       "grid_delete") as verb:
                    self._pick(key, "Delete")
                self.assertTrue(verb.called)

    def test_UPDATE_PREVIEW_goes_through_the_panels_one_entry_point(self):
        for key in ("material", "file"):
            with self.subTest(section=key):
                with mock.patch.object(type(self.panel),
                                       "grid_update_preview") as verb:
                    self._pick(key, "Update Preview")
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
