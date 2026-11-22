"""One colour action per area; each section titles its picker; the three stores stay separate."""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import category  # noqa: E402
from amaze.sections import file as file_section  # noqa: E402
from amaze.tests import test_support  # noqa: E402


class EveryContextNamesItsColourPicker(unittest.TestCase):

    def test_each_one_names_its_own_picker(self):
        """A location is not a category, and the picker's title is the only text that shows it."""
        self.assertEqual("Location Color", file_section.FileSection.colour_title)
        for name in ("AssetSection", "GradientSection"):
            self.assertEqual("Category Color",
                             test_support.section_class(name).colour_title)


class TheColourIsAppliedInBOTHPlacesItIsPainted(unittest.TestCase):
    """A sidebar colour paints the row and every tile in it; setting it must repaint both."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _sidebar_row(self, key):
        panel = self.panel
        panel.section_tabs.setChecked(key)
        QtWidgets.QApplication.processEvents()
        model = panel.cat_list.model()
        self.assertIsNotNone(model, "the %s tab has no sidebar" % key)
        # Row 0 is All in every family - a view, never a category.
        self.assertGreater(model.rowCount(), 1,
                           "the %s sidebar has only All, so there is "
                           "nothing to colour" % key)
        row = getattr(model, "_offset", lambda: 1)()    # File puts a scene row first
        return panel.pane.active_section(), model, model.index(row, 0)

    def test_the_model_EMITS_a_change_signal_so_the_row_repaints(self):
        """These models read the store live, so only a change signal proves the row repaints."""
        for key in ("material", "gradient", "file"):
            with self.subTest(section=key):
                context, model, index = self._sidebar_row(key)
                name = context.sidebar_key(index)
                self.addCleanup(context.set_sidebar_colour, name, "")
                seen = []
                for signal in (model.dataChanged, model.modelReset,
                               model.layoutChanged):
                    def record(*_args, s=signal, seen=seen):    # defaults bind this signal and list now
                        seen.append(s)
                    signal.connect(record)
                    self.addCleanup(signal.disconnect, record)

                context.set_sidebar_colour(name, "#4af2a1")
                QtWidgets.QApplication.processEvents()

                self.assertTrue(
                    seen,
                    "no change signal reached the %s sidebar, so "
                    "the colour appears only after something else "
                    "happens to refresh it" % key)
                self.assertEqual(
                    "#4af2a1", context.sidebar_colour(name),
                    "%s did not store the colour" % key)
                self.assertEqual(
                    "#4af2a1",
                    str(model.index(index.row(), 0).data(
                        category.SIDEBAR_COLOR_ROLE) or ""),
                    "the %s sidebar row does not paint it" % key)

                context.set_sidebar_colour(name, "")
                QtWidgets.QApplication.processEvents()

                self.assertEqual("", context.sidebar_colour(name))
                self.assertEqual(
                    "",
                    str(model.index(index.row(), 0).data(
                        category.SIDEBAR_COLOR_ROLE) or ""),
                    "the %s row still shows the cleared colour" % key)

    def test_an_UNDERSCORE_category_is_coloured_by_its_stored_name(self):
        """Colour is keyed by the stored name, not the displayed one; driven through the panel gesture."""
        panel = self.panel
        panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        categories = panel.pane.category_model
        if categories._row_of("_WIP") is None:
            categories.check_add_category("_WIP")
        self.addCleanup(categories.remove_category, "_WIP")
        QtWidgets.QApplication.processEvents()

        context = panel.pane.active_section()
        self.addCleanup(context.set_sidebar_colour, "_WIP", "")
        context.set_sidebar_colour("_WIP", "#4af2a1")

        self.assertEqual("#4af2a1", context.sidebar_colour("_WIP"))
        self.assertEqual(
            "", context.sidebar_colour("WIP"),
            "the colour was written under the DISPLAYED name, which no "
            "row is keyed by")

        row = panel.cat_list.model().mapFromSource(
            panel.pane.category_model.index(
                panel.pane.category_model._row_of("_WIP"), 0)) \
            if hasattr(panel.cat_list.model(), "mapFromSource") \
            else panel.pane.category_model.index(
                panel.pane.category_model._row_of("_WIP"), 0)
        panel.cat_list.selectionModel().select(
            row, QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.assertEqual(
            "WIP", row.data(),
            "the row does not display the stripped name, so this is not "
            "reproducing the conditions")

        panel.pane.sidebar.set_colour(pick=False)

        self.assertEqual(
            "", context.sidebar_colour("_WIP"),
            "Clear Color cleared a colour keyed by the DISPLAYED name, "
            "so the stored one is still there and the row still shows "
            "it")


if __name__ == "__main__":
    unittest.main()
