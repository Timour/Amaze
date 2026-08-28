"""The Sidebar area: a row acts on the name it STORES, never the one it displays. DisplayRole strips a leading underscore - the mechanism that makes `_All` sort first and read as All - so a caller reading `index.data()` gets a name no asset carries, and the grid empties with the row still highlighted. ▸archive/test_sidebar_area.py
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import category  # noqa: E402
from amaze.panel import sections  # noqa: E402

PACKAGE = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))
from amaze.tests import test_support  # noqa: E402


class _Recorder:
    """Stands in for the grid proxy, remembering the filter it was given. The REAL Categories model sits beside it - the underscore strip lives in its `data()`, so a stub model would test the stub."""

    def __init__(self):
        self.filters = []

    def setFilter(self, role, value):
        self.filters.append((role, value))

    def removeFilter(self, role):
        self.filters.append((role, None))


class _Model:
    CategoryRole = QtCore.Qt.ItemDataRole.UserRole + 1


class _CatList:
    """Only what the name reader asks of the sidebar widget - which model it is showing."""

    def __init__(self, model):
        self._model = model

    def model(self):
        return self._model


class _Panel:
    """The real name reader, borrowed rather than reimplemented, since a copy would pin the copy. Wired to the PROXY as in production - the reader falls back to DisplayRole when a model has no source, so a stub would pass while the defect stood."""

    from amaze.panel.panel import MatLibPanel as _Real
    _raw_category_name = _Real._raw_category_name

    def __init__(self, proxy):
        self.cat_list = _CatList(proxy)


class _Section(sections.AssetSection):
    """An AssetSection whose stack is the recorder above - `select_category` is inherited, and it is the method under test."""

    def __init__(self, categories, proxy, sidebar_proxy):
        self._categories = categories
        self._proxy = proxy
        self._model = _Model()
        self.panel = _Panel(sidebar_proxy)

    def stack(self):
        # The LABELLED shape the real one returns - a bare tuple would drift.
        return sections.AssetStack(
            model=self._model, proxy=self._proxy,
            selection=None, categories=self._categories)


class ARowActsOnTheNameItStores(unittest.TestCase):

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.prefs = test_support.fixture_prefs(self)
        self.categories = category.Categories(preferences=self.prefs)
        # The sidebar shows the PROXY, exactly as the panel wires it.
        self.sidebar = category.CategoriesSidebarProxy()
        self.sidebar.setSourceModel(self.categories)
        self.sidebar.setSortRole(self.categories.CatSortRole)
        self.sidebar.sort(0)
        self.proxy = _Recorder()
        self.section = _Section(self.categories, self.proxy, self.sidebar)

    def _row_for(self, stored):
        """The sidebar row holding `stored`, as a PROXY index - what a click actually hands over. Fails rather than skips when it cannot be made, because a pin that can skip is not a pin."""
        row = self.categories._row_of(stored)
        if row is None:
            self.categories.check_add_category(stored)
            row = self.categories._row_of(stored)
        self.assertIsNotNone(
            row, "could not put %r in the sidebar, so this test cannot "
                 "say anything about it" % stored)
        return self.sidebar.mapFromSource(self.categories.index(row, 0))

    def test_an_underscore_category_filters_on_its_STORED_name(self):
        """`index.data()` is DisplayRole, where the leading underscore is stripped - so a stored `_WIP` filters on a name no asset carries."""
        index = self._row_for("_WIP")
        self.assertEqual(
            "WIP", index.data(),
            "the model no longer strips the underscore for display, so "
            "this test is not reproducing the conditions it exists for")

        self.section.select_category(index)

        self.assertEqual(
            [(_Model.CategoryRole, "_WIP")], self.proxy.filters,
            "the sidebar filtered the grid on the DISPLAYED name, which "
            "no asset carries - the grid goes empty with the row still "
            "highlighted")

    def test_an_ordinary_category_is_unaffected(self):
        """The half that stops the fix over-reaching - a name with no underscore filters on itself."""
        index = self._row_for("Metal")
        self.section.select_category(index)
        self.assertEqual([(_Model.CategoryRole, "Metal")], self.proxy.filters)

    def test_the_All_row_still_clears_the_filter(self):
        """`_All` is the one stored underscore name that MUST resolve to the everything-filter - reading it naively filters on the literal and shows nothing."""
        row = self.categories._row_of("_All")
        self.assertIsNotNone(
            row, "the fixture has no _All row, so this cannot test the "
                 "case the underscore mechanism exists for")
        index = self.sidebar.mapFromSource(self.categories.index(row, 0))
        self.assertEqual("All", index.data())

        self.section.select_category(index)

        self.assertEqual(
            [(_Model.CategoryRole, "")], self.proxy.filters,
            "clicking All did not clear the filter, so the grid shows "
            "one category (or nothing) when it should show everything")


class WhatMayBeDroppedOnASidebarRowIsTheCONTEXTsAnswer(unittest.TestCase):
    """What a sidebar row accepts is the CONTEXT's answer, never a branch on a section key - a tuple of keys is a list someone has to remember to update when a section arrives."""

    def test_every_context_answers_whether_it_takes_drops(self):
        for name in ("MaterialSection", "CopSection", "CodeSection",
                     "GradientSection"):
            with self.subTest(context=name):
                self.assertTrue(
                    getattr(sections, name).takes_category_drops,
                    "%s has categories and refuses tiles dropped on "
                    "them" % name)

    def test_FILE_takes_none(self):
        """Its rows are registered folders - a file's location is where it sits on disk, not something a drag can change."""
        self.assertFalse(sections.FileSection.takes_category_drops)

    def test_the_ONLINE_world_takes_none_either(self):
        """A sidebar of SOURCES - a remote catalogue's categories are not ours to write to."""
        self.assertFalse(sections.OnlineContext.takes_category_drops)

    def test_the_panel_no_longer_holds_a_list_of_section_KEYS(self):
        """A tuple of section keys is a list someone has to remember to update, and a section that is forgotten simply misses the behaviour."""
        with open(os.path.join(PACKAGE, "panel", "panel.py"),
                  encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn(
            "CATEGORY_SECTIONS", source,
            "the panel still keeps its own list of which sections have "
            "categories")

    def test_the_cluster_does_not_branch_on_a_section_key(self):
        """Read as STRUCTURE, not prose - the module may name a key in a comment, but no code in it may COMPARE against one. Every string under the comparison counts, or a tuple form slips past."""
        import ast
        with open(os.path.join(PACKAGE, "panel", "sidebar.py"),
                  encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        keys = {"material", "cop", "code", "gradient", "file", "online"}
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            for side in [node.left] + list(node.comparators):
                for inner in ast.walk(side):
                    if (isinstance(inner, ast.Constant)
                            and inner.value in keys):
                        offenders.append(inner.value)
        self.assertEqual(
            [], offenders,
            "panel/sidebar.py compares against section keys %s - the "
            "context answers for itself" % offenders)

    def test_COLOR_still_guards_its_synthetic_rows(self):
        """The one rule that is genuinely per-context survives the move - a gradient row must be a real user category."""
        section = sections.GradientSection.__new__(sections.GradientSection)
        section.panel = type("_P", (), {
            "gradient_model": type("_M", (), {
                "user_categories": staticmethod(lambda: ["Warm"])})()})()
        self.assertTrue(section.accepts_category_drop(None, "Warm"))
        self.assertFalse(
            section.accepts_category_drop(None, "Wada 3 Colors"),
            "a synthetic palette row accepted a dropped tile")

    def test_the_base_answer_is_permissive(self):
        """The shared rules already reject what matters, so a context with nothing extra to say says nothing."""
        self.assertTrue(
            sections.AssetSection.accepts_category_drop(None, None, "Metal"))


if __name__ == "__main__":
    unittest.main()
