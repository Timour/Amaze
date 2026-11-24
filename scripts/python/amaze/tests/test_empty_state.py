"""A star toggled over a favourites-only grid acts on the rows picked, though rows drop out."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # the first QApplication picks the platform
from PySide6 import QtWidgets

from amaze.panel import grid
from amaze.tests import test_support

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class AFavouriteFlipActsOnThePickedRows(unittest.TestCase):
    """Under favourites-only a flip drops its proxy row, so every row is mapped before any flip."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        view = grid.visible_view(self.panel)
        proxy = view.model() if view is not None else None
        if proxy is None or not proxy.rowCount():
            self.skipTest("the fixture library has no rows")
        self.proxy = proxy
        self.source = proxy.sourceModel()
        self.role = self.source.FavoriteRole

    def _favourites_only(self, on):
        self.panel.cb_favsonly.setChecked(on)
        QtWidgets.QApplication.processEvents()

    def test_unstarring_a_multi_selection_unstars_the_selected_rows(self):
        starred = [self.proxy.index(r, 0) for r in range(self.proxy.rowCount())
                   if self.proxy.index(r, 0).data(self.role)]
        if starred:
            self.panel.pane.assets.toggle_favourite(starred)
        QtWidgets.QApplication.processEvents()
        self.panel.pane.assets.toggle_favourite([self.proxy.index(0, 0),
                                                 self.proxy.index(1, 0)])
        QtWidgets.QApplication.processEvents()
        self._favourites_only(True)
        self.addCleanup(self._favourites_only, False)
        self.assertEqual(2, self.proxy.rowCount(),
                         "premise: two favourites showing")
        self.panel.pane.assets.toggle_favourite([self.proxy.index(0, 0),
                                                 self.proxy.index(1, 0)])
        QtWidgets.QApplication.processEvents()
        left = sum(1 for r in range(self.source.rowCount())
                   if self.source.index(r, 0).data(self.role))
        self.assertEqual(0, left,
                         "unstarring both favourites left %d starred - "
                         "the loop toggled through stale proxy rows"
                         % left)


if __name__ == "__main__":
    unittest.main()
