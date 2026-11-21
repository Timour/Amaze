"""Category colours are keyed by name: a rename keeps the colour and a removal deletes it."""

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
        before = test_support.asset_ids(self.model)
        node_actions.add_asset(self.model, lop, cat, "", False, name="Coloured")
        lop.destroy()
        saved, = test_support.arrived(self.model, before)
        return self.model.find_asset_row_by_id(saved.mat_id)

    def test_an_uncoloured_or_uncategorised_tile_has_no_colour(self):
        self.assertEqual("", self.model.category_color(self.row),
                         "an uncoloured category coloured its tile")
        row = self._an_asset("")
        self.cats.set_color("Metal", "#4af2a1")
        self.assertEqual("", self.model.category_color(row),
                         "an asset with no category took a colour")

    def test_the_colour_reaches_the_grid(self):
        """Asset and category models share one connector's data, so the grid sees the sidebar's edit."""
        self.cats.set_color("Metal", "#4af2a1")
        self.assertEqual("#4af2a1", self.model.category_color(self.row))
        self.assertEqual("#4af2a1", self.model.data(
            self.model.index(self.row, 0), self.model.CategoryColorRole))
        row = self.cats._categories.index("Metal")
        self.assertEqual("#4af2a1", self.cats.data(
            self.cats.index(row, 0), category.SIDEBAR_COLOR_ROLE))

    def test_a_rename_keeps_the_colour_under_the_new_name(self):
        self.cats.set_color("Metal", "#4af2a1")
        self.cats.rename_category("Metal", "Metals")
        self.assertEqual("#4af2a1", self.cats.color_of("Metals"))
        self.assertEqual("", self.cats.color_of("Metal"))

    def test_removing_a_category_removes_its_colour(self):
        """Otherwise the stored colour is applied to the next category created with the same name."""
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

    def test_the_colour_is_kept_after_a_reload_from_disk(self):
        self.cats.set_color("Metal", "#e28248")
        test_support.reset_database_singletons()
        fresh = cop_library.CopCategories(preferences=self.prefs)
        self.assertEqual("#e28248", fresh.color_of("Metal"))


if __name__ == "__main__":
    unittest.main()
