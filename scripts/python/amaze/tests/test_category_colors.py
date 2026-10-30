"""A category carries a colour and the grid paints it under every tile in that category - unambiguous only because an asset has exactly ONE category. The colour is keyed by NAME, so a rename must carry it and a removal must take it, or an orphan key reattaches when the name returns. ▸archive/test_category_colors.py
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtGui, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.actions import nodes as node_actions  # noqa: E402
from amaze.core import category, cop_library  # noqa: E402
from amaze.panel import delegates  # noqa: E402
from amaze.tests import test_support  # noqa: E402 - redirects the log


class CategoryColorTest(unittest.TestCase):

    def setUp(self):
        test_support.reset_database_singletons()
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.render_on_import = 0
        self.cats = cop_library.CopCategories(preferences=self.prefs)
        self.model = cop_library.CopLibrary(preferences=self.prefs)
        self.addCleanup(test_support.clear_obj)
        self.row = self._an_asset("Metal")
        self.cats.check_add_category("Metal")

    def _an_asset(self, cat: str) -> int:
        lop = hou.node("/obj").createNode("lopnet", "cc_src")
        lop.createNode("sphere")
        held = test_support.asset_ids(self.model)
        node_actions.add_asset(self.model, lop, cat, "", False, name="Coloured")
        lop.destroy()
        saved, = test_support.arrived(self.model, held)
        return self.model.find_asset_row_by_id(saved.mat_id)

    def test_an_uncoloured_or_uncategorised_tile_has_no_colour(self):
        self.assertEqual("", self.model.category_color(self.row),
                         "an uncoloured category coloured its tile")
        row = self._an_asset("")
        self.cats.set_color("Metal", "#4af2a1")
        self.assertEqual("", self.model.category_color(row),
                         "an asset with no category took a colour")

    def test_the_colour_reaches_the_grid(self):
        """The asset model and the category model share one connector's data, so the grid sees the sidebar's edit with nothing wired between them."""
        self.cats.set_color("Metal", "#4af2a1")
        self.assertEqual("#4af2a1", self.model.category_color(self.row))
        self.assertEqual("#4af2a1", self.model.data(
            self.model.index(self.row, 0), self.model.CategoryColorRole))
        row = self.cats._categories.index("Metal")
        self.assertEqual("#4af2a1", self.cats.data(
            self.cats.index(row, 0), category.SIDEBAR_COLOR_ROLE))

    def test_a_rename_carries_the_colour_across(self):
        self.cats.set_color("Metal", "#4af2a1")
        self.cats.rename_category("Metal", "Metals")
        self.assertEqual("#4af2a1", self.cats.color_of("Metals"))
        self.assertEqual("", self.cats.color_of("Metal"))

    def test_a_removed_category_takes_its_colour_with_it(self):
        """Otherwise the colour lies in wait and reattaches to the next category reusing the name."""
        self.cats.set_color("Metal", "#4af2a1")
        self.cats.remove_category("Metal")
        self.cats.check_add_category("Metal")
        self.assertEqual("", self.cats.color_of("Metal"),
                         "a deleted category's colour came back")

    def test_clearing_removes_the_colour(self):
        self.cats.set_color("Metal", "#4af2a1")
        self.cats.set_color("Metal", "")
        self.assertEqual("", self.cats.color_of("Metal"))
        self.assertEqual("", self.model.category_color(self.row))

    def test_it_survives_a_reload_from_disk(self):
        self.cats.set_color("Metal", "#e28248")
        test_support.reset_database_singletons()
        fresh = cop_library.CopCategories(preferences=self.prefs)
        self.assertEqual("#e28248", fresh.color_of("Metal"))


class BandTextTest(unittest.TestCase):
    """The name and subtitle have to stay readable on any colour."""

    def test_light_bands_get_dark_text_and_dark_bands_light(self):
        text_on = delegates.AssetItemDelegate.text_on
        dark = delegates.AssetItemDelegate.BAND_TEXT_DARK
        light = delegates.AssetItemDelegate.BAND_TEXT_LIGHT
        for colour, expected in (
            ("#4af2a1", dark),      # mint
            ("#e2b148", dark),      # sand
            ("#ffffff", dark),
            ("#20304f", light),     # navy
            ("#262626", light),
            ("#000000", light),
            ("#00ff00", dark),      # weighted, never averaged: green reads far brighter than blue
            ("#0000ff", light),
        ):
            self.assertEqual(
                expected.name(), text_on(QtGui.QColor(colour)).name(),
                "wrong text colour on %s" % colour)


if __name__ == "__main__":
    unittest.main()
