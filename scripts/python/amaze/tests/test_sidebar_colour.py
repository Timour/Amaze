"""One colour gesture for the Sidebar, three answers behind it.

BATCH 7 of the four-areas restructure, the second half. Set Color /
Clear Color was written three times - once per sidebar menu - and each
copy carried the whole gesture: read the current colour out of its own
store, open the picker with its own copy of the default `#4af2a1`, and
repaint its own two models afterwards.

They also disagreed about the one thing the first half of this batch
was about: the asset path reads the STORED name through
`_raw_category_name` (a category shown as "WIP" is stored "_WIP"), and
the other two read whatever their menu happened to be holding.

The gesture belongs to the area; what a colour IS belongs to the
context. Three stores stay three stores - a category colour lives in
the library, a palette category's in gradients.json, a location's in
prefs, and moving them is a storage question nobody has asked yet.
"""

import ast
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
from amaze.tests import test_support  # noqa: E402

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Every context with a sidebar whose rows can carry a colour.
COLOURED = ("AssetSection", "FileSection", "GradientSection")


class EveryContextSaysWhatAColourIs(unittest.TestCase):

    def test_each_one_reads_and_writes_its_own(self):
        for name in COLOURED:
            with self.subTest(context=name):
                context = getattr(sections, name)
                for verb in ("sidebar_colour", "set_sidebar_colour"):
                    self.assertTrue(
                        hasattr(context, verb),
                        "%s has no %s, so the panel has to know which "
                        "store to reach for" % (name, verb))

    def test_each_one_names_its_own_picker(self):
        """A location is not a category, and the picker's title is the
        only place that shows."""
        self.assertEqual("Location Color", sections.FileSection.colour_title)
        for name in ("AssetSection", "GradientSection"):
            self.assertEqual("Category Color",
                             getattr(sections, name).colour_title)


class ThePickerOpensFromONEPlace(unittest.TestCase):

    def _panel_tree(self):
        with open(os.path.join(PACKAGE, "panel", "panel.py"),
                  encoding="utf-8") as handle:
            return ast.parse(handle.read())

    def test_no_sidebar_menu_opens_the_picker_itself(self):
        tree = self._panel_tree()
        offenders = []
        for func in ast.walk(tree):
            if not (isinstance(func, ast.FunctionDef)
                    and func.name.endswith("catlist_menu")):
                continue
            for call in ast.walk(func):
                if (isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "pick_color"):
                    offenders.append("%s:%d" % (func.name, call.lineno))
        self.assertEqual(
            [], offenders,
            "a sidebar menu still runs the whole colour gesture itself, "
            "at %s" % offenders)

    def test_the_default_colour_is_written_once(self):
        """Three copies of a hex literal is three places to change it,
        and the sabotage that finds a stale one is a person noticing
        months later."""
        with open(os.path.join(PACKAGE, "panel", "panel.py"),
                  encoding="utf-8") as handle:
            panel_source = handle.read()
        self.assertLessEqual(
            panel_source.count("#4af2a1"), 1,
            "the picker's default colour is spelled out more than once "
            "in panel.py")


class TheColourReachesBOTHPlacesItIsPainted(unittest.TestCase):
    """A sidebar colour is painted twice: on the sidebar row itself
    (SIDEBAR_COLOR_ROLE, one role for all three families) and on every
    tile filed under it. A gesture that writes the store but repaints
    only one of them looks like it did nothing."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _sidebar_row(self, key):
        panel = self.panel
        panel.section_tabs.setChecked(key)
        QtWidgets.QApplication.processEvents()
        model = panel.cat_list.model()
        self.assertIsNotNone(model, "the %s tab has no sidebar" % key)
        # Row 0 is All in every family - a view, not a category, and
        # colouring it would mean colouring everything.
        self.assertGreater(model.rowCount(), 1,
                           "the %s sidebar has only All, so there is "
                           "nothing to colour" % key)
        return panel._section(), model, model.index(1, 0)

    def test_a_colour_shows_on_the_row_and_on_its_tiles(self):
        for key in ("material", "gradient", "file"):
            with self.subTest(section=key):
                context, model, index = self._sidebar_row(key)
                name = context.sidebar_key(index)
                self.addCleanup(context.set_sidebar_colour, name, "")

                context.set_sidebar_colour(name, "#4af2a1")
                QtWidgets.QApplication.processEvents()

                self.assertEqual(
                    "#4af2a1", context.sidebar_colour(name),
                    "%s did not store the colour" % key)
                self.assertEqual(
                    "#4af2a1",
                    str(model.index(1, 0).data(
                        category.SIDEBAR_COLOR_ROLE) or ""),
                    "the %s sidebar row does not paint it" % key)

    def test_the_sidebar_is_TOLD_so_the_row_actually_repaints(self):
        """Reading the role back is not enough: these models answer it
        live from the store, so a gesture that wrote and told nobody
        reads correct and shows nothing until the next unrelated
        refresh. The signal IS the repaint."""
        for key in ("material", "gradient", "file"):
            with self.subTest(section=key):
                context, model, index = self._sidebar_row(key)
                name = context.sidebar_key(index)
                self.addCleanup(context.set_sidebar_colour, name, "")
                told = []
                for signal in (model.dataChanged, model.modelReset,
                               model.layoutChanged):
                    signal.connect(lambda *a, s=signal: told.append(s))

                context.set_sidebar_colour(name, "#4af2a1")
                QtWidgets.QApplication.processEvents()

                self.assertTrue(
                    told,
                    "nothing told the %s sidebar its row changed, so "
                    "the colour appears only after something else "
                    "happens to refresh it" % key)

    def test_clearing_it_takes_it_off_the_row(self):
        for key in ("material", "gradient", "file"):
            with self.subTest(section=key):
                context, model, index = self._sidebar_row(key)
                name = context.sidebar_key(index)
                context.set_sidebar_colour(name, "#4af2a1")
                QtWidgets.QApplication.processEvents()

                context.set_sidebar_colour(name, "")
                QtWidgets.QApplication.processEvents()

                self.assertEqual("", context.sidebar_colour(name))
                self.assertEqual(
                    "",
                    str(model.index(1, 0).data(
                        category.SIDEBAR_COLOR_ROLE) or ""),
                    "the %s row still wears the cleared colour" % key)

    def test_an_UNDERSCORE_category_is_coloured_by_its_stored_name(self):
        """The first half of this batch, in the colour gesture: the
        sidebar DISPLAYS "_WIP" as "WIP", and a colour written under
        the displayed name is one nothing ever reads - plus an orphan
        key that reattaches if the name comes back."""
        panel = self.panel
        panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        categories = panel.category_model
        if categories._row_of("_WIP") is None:
            categories.check_add_category("_WIP")
        self.addCleanup(categories.remove_category, "_WIP")
        QtWidgets.QApplication.processEvents()

        context = panel._section()
        self.addCleanup(context.set_sidebar_colour, "_WIP", "")
        context.set_sidebar_colour("_WIP", "#4af2a1")

        self.assertEqual("#4af2a1", context.sidebar_colour("_WIP"))
        self.assertEqual(
            "", context.sidebar_colour("WIP"),
            "the colour was written under the DISPLAYED name, which no "
            "row is keyed by")

        # THROUGH THE PANEL'S GESTURE, which is where the name is read:
        # Clear Color on the selected row. Calling the context directly
        # (above) never exercises that read - the sabotage round found
        # exactly that hole.
        row = panel.cat_list.model().mapFromSource(
            panel.category_model.index(
                panel.category_model._row_of("_WIP"), 0)) \
            if hasattr(panel.cat_list.model(), "mapFromSource") \
            else panel.category_model.index(
                panel.category_model._row_of("_WIP"), 0)
        panel.cat_list.selectionModel().select(
            row, QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.assertEqual(
            "WIP", row.data(),
            "the row does not display the stripped name, so this is not "
            "reproducing the conditions")

        panel.sidebar_set_colour(pick=False)

        self.assertEqual(
            "", context.sidebar_colour("_WIP"),
            "Clear Color cleared a colour keyed by the DISPLAYED name, "
            "so the stored one is still there and the row still wears "
            "it")


if __name__ == "__main__":
    unittest.main()
