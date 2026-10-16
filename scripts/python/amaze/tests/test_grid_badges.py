"""A badge that is not DRAWN cannot be CLICKED, and one with no click WIRED is no button."""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.panel import delegates  # noqa: E402
from amaze.tests import test_support  # noqa: E402

VERSIONS_ROLE = QtCore.Qt.ItemDataRole.UserRole + 30
SUBTITLE_ROLE = QtCore.Qt.ItemDataRole.UserRole + 31
FAVORITE_ROLE = QtCore.Qt.ItemDataRole.UserRole + 32

TILE = 128


def _view_option(view):
    """One grid tile's option on `view`."""
    view.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
    option = QtWidgets.QStyleOptionViewItem()
    option.widget = view
    option.rect = QtCore.QRect(0, 0, TILE, TILE)
    option.decorationPosition = QtWidgets.QStyleOptionViewItem.Position.Top
    return option


def _release(point):
    """A left-button release at `point`."""
    return QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonRelease, QtCore.QPointF(point),
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier)


class _Rows(QtCore.QAbstractListModel):
    """One row, with two versions - the only state the badge needs."""

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else 1

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return "asset"
        if role == VERSIONS_ROLE:
            return 2
        if role == SUBTITLE_ROLE:
            return "Karma"
        return None


class TheVersionsBadgeAnswersOnlyWhereItIsDrawn(unittest.TestCase):

    def setUp(self):
        self.clicked = []
        self.model = _Rows()
        self.view = QtWidgets.QListView()
        self.view.setModel(self.model)
        self.delegate = test_support.tile_delegate({"versions": VERSIONS_ROLE}, SUBTITLE_ROLE)
        self.delegate.set_badge_click("versions", self.clicked.append)
        self.view.setItemDelegate(self.delegate)
        self.addCleanup(self.view.deleteLater)

    def _release_on_the_badge(self, option):
        """A left-button release at the centre of the badge's rect."""
        rect = self.delegate._badge_rect(option.rect, "versions")
        return _release(rect.center())

    def test_a_click_on_the_badge_opens_versions_in_GRID_mode(self):
        option = _view_option(self.view)
        index = self.model.index(0, 0)
        handled = self.delegate.editorEvent(
            self._release_on_the_badge(option), self.model, option, index)
        self.assertTrue(handled, "the badge did not take the click")
        self.assertEqual(1, len(self.clicked),
                         "the versions dialog was not asked for")


class _StarRows(QtCore.QAbstractListModel):
    """One row whose favourite state the test flips."""

    def __init__(self):
        super().__init__()
        self.favourite = False

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else 1

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return "asset"
        if role == FAVORITE_ROLE:
            return self.favourite
        if role == SUBTITLE_ROLE:
            return "Karma"
        return None


class TheStarBadgeIsAButtonInBOTHItsStates(unittest.TestCase):
    """The always-visible star: a click toggles a plain tile AND a favourite one - and a delegate with no click wired (the online grid) offers no button over the same pixels."""

    def setUp(self):
        self.clicked = []
        self.model = _StarRows()
        self.view = QtWidgets.QListView()
        self.view.setModel(self.model)
        self.delegate = test_support.tile_delegate({"favourite": FAVORITE_ROLE}, SUBTITLE_ROLE)
        self.delegate.set_badge_click("favourite", self.clicked.append)
        self.view.setItemDelegate(self.delegate)
        self.addCleanup(self.view.deleteLater)

    def _click_the_star(self, delegate, option):
        rect = delegate._badge_rect(option.rect, "favourite")
        return delegate.editorEvent(
            _release(rect.center()), self.model, option,
            self.model.index(0, 0))

    def test_a_click_stars_a_tile_that_is_NOT_yet_a_favourite(self):
        """The new half: the badge answers while its role is FALSY - the resting star is a button, not an indicator that happens to be dim."""
        option = _view_option(self.view)
        self.assertTrue(self._click_the_star(self.delegate, option),
                        "the resting star did not take the click")
        self.assertEqual(1, len(self.clicked),
                         "the favourite toggle was never asked for")

    def test_a_click_unstars_a_tile_that_IS_one(self):
        self.model.favourite = True
        option = _view_option(self.view)
        self.assertTrue(self._click_the_star(self.delegate, option),
                        "the amber star did not take the click")
        self.assertEqual(1, len(self.clicked))

    def test_an_UNWIRED_delegate_offers_no_star_button(self):
        """The online grid: same role wired, no click - a click there must fall through to plain selection, because a button that does nothing is a lie."""
        bare = test_support.tile_delegate({"favourite": FAVORITE_ROLE}, SUBTITLE_ROLE)
        self.view.setItemDelegate(bare)
        option = _view_option(self.view)
        self.assertFalse(self._click_the_star(bare, option),
                         "a delegate with no click wired swallowed the "
                         "click anyway")


NOTES_ROLE = QtCore.Qt.ItemDataRole.UserRole + 33


class _NotedRow(QtCore.QAbstractListModel):
    """One row carrying a comment."""

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else 1

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            return "asset"
        if role == NOTES_ROLE:
            return True
        if role == SUBTITLE_ROLE:
            return "Karma"
        return None


class TheCommentBadgeIsAButton(unittest.TestCase):
    """Clicking the comment badge OPENS the Comments pane - one-way, never closing - through the toolbar chip, one path to one state."""

    def test_a_wired_comment_badge_takes_the_click(self):
        clicked = []
        view = QtWidgets.QListView()
        self.addCleanup(view.deleteLater)
        model = _NotedRow()
        view.setModel(model)
        delegate = test_support.tile_delegate({"comment": NOTES_ROLE}, SUBTITLE_ROLE)
        delegate.set_badge_click("comment", clicked.append)
        view.setItemDelegate(delegate)
        option = _view_option(view)
        index = model.index(0, 0)
        rect = delegate._badge_rect(option.rect, "comment")
        handled = delegate.editorEvent(
            _release(rect.center()), model, option, index)
        self.assertTrue(handled, "the comment badge swallowed nothing")
        self.assertEqual([index], clicked)

    def test_a_commentless_tile_shows_the_outline_badge_like_the_heart(self):
        row = next(b for b in delegates.BADGES if b.name == "comment")
        self.assertEqual("badge_comment", row.art)
        self.assertTrue(row.dims, "it does not wear the family's rest and hover strength")
        self.assertFalse(row.hover_art, "the filled bubble grew a second art for hover")
        self.assertEqual("badge_comment_off", row.off_art,
                         "a tile with no comments shows no badge")
        self.assertEqual("badge_comment_off_hover", row.off_hover_art,
                         "the outline badge does not colour under the pointer")


class TheCommentBadgeOpensThePane(unittest.TestCase):
    """The handler behind the badge: it opens the Comments pane, never closes it, and leaves a multi-selection standing."""

    @classmethod
    def setUpClass(cls):
        from amaze.tests import test_support
        cls.panel = test_support.fixture_panel(
            test_support.class_scope(cls))

    def test_the_click_opens_the_pane_one_way(self):
        panel = self.panel
        panel.btn_notes.setChecked(False)
        index = panel.material_sorted_model.index(0, 0)
        panel._open_comments_from_badge(index)
        self.assertTrue(panel.btn_notes.isChecked(),
                        "the badge click did not open the pane")
        panel._open_comments_from_badge(index)
        self.assertTrue(panel.btn_notes.isChecked(),
                        "a second click CLOSED the pane - the badge "
                        "only ever opens")
        current = panel.thumblist.selectionModel().currentIndex()
        self.assertEqual(index.row(), current.row(),
                         "the clicked tile did not become the "
                         "current row, so the pane shows the wrong "
                         "comments")

    def test_a_badge_inside_a_multi_selection_keeps_it(self):
        """The star button's law, one badge over: the pane reads the CURRENT row, so collapsing a hand-built selection buys nothing and costs the user the selection."""
        panel = self.panel
        model = panel.material_sorted_model
        if model.rowCount() < 3:
            self.skipTest("the fixture library has fewer than 3 rows")
        flags = QtCore.QItemSelectionModel.SelectionFlag
        selection = panel.thumblist.selectionModel()
        rows = [model.index(r, 0) for r in range(3)]
        selection.clearSelection()
        for index in rows:
            selection.select(index, flags.Select)

        panel._open_comments_from_badge(rows[2])

        self.assertEqual(
            3, len(selection.selectedIndexes()),
            "clicking the comment badge on a selected tile threw away "
            "the rest of the selection")
        self.assertEqual(
            rows[2].row(), selection.currentIndex().row(),
            "the clicked tile did not become the current row")

    def test_a_badge_OUTSIDE_the_selection_takes_it_over(self):
        panel = self.panel
        model = panel.material_sorted_model
        if model.rowCount() < 3:
            self.skipTest("the fixture library has fewer than 3 rows")
        flags = QtCore.QItemSelectionModel.SelectionFlag
        selection = panel.thumblist.selectionModel()
        selection.select(model.index(0, 0), flags.ClearAndSelect)

        panel._open_comments_from_badge(model.index(2, 0))

        self.assertEqual(
            [2], [i.row() for i in selection.selectedIndexes()],
            "a badge on a tile outside the selection must select that "
            "tile, the way a plain click does")


if __name__ == "__main__":
    unittest.main()
