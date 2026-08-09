"""The Sidebar area: a row acts on the name it STORES.

BATCH 7 of the four-areas restructure. The defect it dissolves: clicking
a category whose stored name begins with an underscore filters the grid
to nothing.

`Categories.data` returns `elem[1:]` for DisplayRole when the stored
name starts with "_" - the mechanism that makes the stored "_All" sort
first and read as "All". So a category stored `_WIP` DISPLAYS as "WIP",
and a caller reading `index.data()` gets a name no asset carries. The
grid goes empty with nothing saying why, and the sidebar row stays
highlighted.

The panel already has the one right answer - `_raw_category_name`,
whose own docstring lists three actions that were broken this exact way
(rename, remove, and drag-to-categorise) and were moved onto it. The
sidebar CLICK was never moved. That is protocol answer 2: it has an
owner, and the fix was being written outside it.

Written BEFORE the fix, and it fails against the shipped code - which
is the strongest form of the sabotage-first rule, because the defect
is real rather than injected.
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
    """Stands in for the grid proxy: remembers what filter it was given.

    The REAL Categories model is used beside it, deliberately - the
    underscore strip lives in its `data()`, and a stub model would test
    the stub."""

    def __init__(self):
        self.filters = []

    def setFilter(self, role, value):
        self.filters.append((role, value))

    def removeFilter(self, role):
        self.filters.append((role, None))


class _Model:
    CategoryRole = QtCore.Qt.ItemDataRole.UserRole + 1


class _CatList:
    """Only what the name reader asks of the sidebar widget: which model
    it is showing."""

    def __init__(self, model):
        self._model = model

    def model(self):
        return self._model


class _Panel:
    """Only what select_category reaches for on the panel: the ONE
    reader of a row's stored name, borrowed from the real class rather
    than reimplemented - a copy here would pin the copy.

    The sidebar is wired to the PROXY, as it is in production. That is
    load-bearing: `_raw_category_name` reads `CatSortRole` through
    `model.sourceModel()` and falls back to DisplayRole when the model
    has no source - so a stub with no cat_list gets the displayed name
    and the test would pass while the defect stood."""

    from amaze.panel.panel import MatLibPanel as _Real
    _raw_category_name = _Real._raw_category_name

    def __init__(self, proxy):
        self.cat_list = _CatList(proxy)


class _Section(sections.AssetSection):
    """An AssetSection whose stack is the recorder above. Nothing else
    about it differs - `select_category` is inherited, which is the
    method under test."""

    def __init__(self, categories, proxy, sidebar_proxy):
        self._categories = categories
        self._proxy = proxy
        self._model = _Model()
        self.panel = _Panel(sidebar_proxy)

    def stack(self):
        # The LABELLED shape the real one returns (2026-08-03) -
        # a bare tuple here would let the stub drift from it.
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
        """The sidebar row holding `stored`, added if the fixture has
        no such category. Fails rather than skips when it cannot be
        made - a pin that can skip is not a pin."""
        row = self.categories._row_of(stored)
        if row is None:
            self.categories.check_add_category(stored)
            row = self.categories._row_of(stored)
        self.assertIsNotNone(
            row, "could not put %r in the sidebar, so this test cannot "
                 "say anything about it" % stored)
        # A PROXY index - what a click actually hands over.
        return self.sidebar.mapFromSource(self.categories.index(row, 0))

    def test_an_underscore_category_filters_on_its_STORED_name(self):
        """THE DEFECT. `index.data()` is DisplayRole, which is where the
        leading underscore is stripped - so clicking `_WIP` filtered the
        grid to "WIP", a name no asset carries, and the grid emptied
        with the row still highlighted and nothing saying why."""
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
        """The half that stops the fix over-reaching: a name with no
        underscore must filter on itself, unchanged."""
        index = self._row_for("Metal")
        self.section.select_category(index)
        self.assertEqual([(_Model.CategoryRole, "Metal")], self.proxy.filters)

    def test_the_All_row_still_clears_the_filter(self):
        """`_All` is the one stored underscore name that MUST resolve to
        the everything-filter - it is the whole reason the strip exists.
        A fix that reads the stored name naively would filter on the
        literal "_All" and show nothing at all."""
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
    """BATCH 7, 2026-08-04. The drag-hover cluster branched on the
    section KEY twice: a `CATEGORY_SECTIONS` tuple of four key strings,
    and `if self.current_section == "gradient"` reaching into
    `gradient_model` by name from inside a shared helper.

    That is the shape batches 4 to 9 took out of activation, the
    toolbar, Comments and both menus - and it was still standing here.
    A sixth section with categories would have had to be remembered in
    a tuple; one without would have had to be kept OUT of it.
    """

    def test_every_context_answers_whether_it_takes_drops(self):
        for name in ("MaterialSection", "CopSection", "CodeSection",
                     "GradientSection"):
            with self.subTest(context=name):
                self.assertTrue(
                    getattr(sections, name).takes_category_drops,
                    "%s has categories and refuses tiles dropped on "
                    "them" % name)

    def test_FILE_takes_none(self):
        """Its rows are registered folders. A file's location is where
        it sits on disk, not something a drag can change."""
        self.assertFalse(sections.FileSection.takes_category_drops)

    def test_the_ONLINE_world_takes_none_either(self):
        """It has a sidebar of SOURCES, and a remote catalogue's
        categories are not ours to write to."""
        self.assertFalse(sections.OnlineContext.takes_category_drops)

    def test_the_panel_no_longer_holds_a_list_of_section_KEYS(self):
        """`CATEGORY_SECTIONS` is the thing this replaces. A tuple of
        keys is a list someone has to remember to update - which is
        exactly how Node and Code missed the sidebar half of the filter
        push (practice.md)."""
        with open(os.path.join(PACKAGE, "panel", "panel.py"),
                  encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn(
            "CATEGORY_SECTIONS", source,
            "the panel still keeps its own list of which sections have "
            "categories")

    def test_the_cluster_does_not_branch_on_a_section_key(self):
        """Read as STRUCTURE, not prose: the module may mention a key
        in a comment, but no code in it may compare against one."""
        import ast
        with open(os.path.join(PACKAGE, "panel", "sidebar.py"),
                  encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        keys = {"material", "cop", "code", "gradient", "file", "online"}
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            # EVERY string under the comparison, not just a bare
            # comparator: `not in ("material", "cop")` puts them in a
            # Tuple, and that is the CATEGORY_SECTIONS shape this test
            # exists to catch. The first version checked only bare
            # constants and a sabotage in exactly that form went green.
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
        """The one rule that is genuinely per-context survives the
        move: a gradient row must be a real user category. It used to
        be an `== "gradient"` branch inside the shared helper."""
        section = sections.GradientSection.__new__(sections.GradientSection)
        section.panel = type("_P", (), {
            "gradient_model": type("_M", (), {
                "user_categories": staticmethod(lambda: ["Warm"])})()})()
        self.assertTrue(section.accepts_category_drop(None, "Warm"))
        self.assertFalse(
            section.accepts_category_drop(None, "Wada 3 Colors"),
            "a synthetic palette row accepted a dropped tile")

    def test_the_base_answer_is_permissive(self):
        """The shared rules already rejected what matters (no context,
        no row, the All row). A context with nothing extra to say says
        nothing."""
        self.assertTrue(
            sections.AssetSection.accepts_category_drop(None, None, "Metal"))


if __name__ == "__main__":
    unittest.main()
