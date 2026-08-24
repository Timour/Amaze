"""A badge that is not DRAWN cannot be CLICKED - list mode paints no badges - and a badge with no click WIRED is not a button at all."""

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

VERSIONS_ROLE = QtCore.Qt.ItemDataRole.UserRole + 30
SUBTITLE_ROLE = QtCore.Qt.ItemDataRole.UserRole + 31
FAVORITE_ROLE = QtCore.Qt.ItemDataRole.UserRole + 32

TILE = 128


def _view_option(view, list_mode, decoration=None):
    """`decoration` must not matter - the list tests run it both ways."""
    view.setViewMode(
        QtWidgets.QListView.ViewMode.ListMode if list_mode
        else QtWidgets.QListView.ViewMode.IconMode)
    option = QtWidgets.QStyleOptionViewItem()
    option.widget = view
    option.rect = QtCore.QRect(0, 0, TILE, TILE)
    option.decorationPosition = decoration or (
        QtWidgets.QStyleOptionViewItem.Position.Left if list_mode
        else QtWidgets.QStyleOptionViewItem.Position.Top)
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
        self.delegate = delegates.AssetItemDelegate(
            SUBTITLE_ROLE, versions_role=VERSIONS_ROLE)
        self.delegate.set_badge_click("versions", self.clicked.append)
        self.view.setItemDelegate(self.delegate)
        self.addCleanup(self.view.deleteLater)

    def _release_on_the_badge(self, option):
        """A left-button release at the centre of the badge's rect."""
        rect = self.delegate._badge_rect(
            option.rect,
            option.decorationPosition
            == QtWidgets.QStyleOptionViewItem.Position.Top,
            delegates.LOWER_LEFT)
        return _release(rect.center())

    def test_a_click_on_the_badge_opens_versions_in_GRID_mode(self):
        """The half that must keep working - list-only coverage passes dead."""
        option = _view_option(self.view, list_mode=False)
        index = self.model.index(0, 0)
        handled = self.delegate.editorEvent(
            self._release_on_the_badge(option), self.model, option, index)
        self.assertTrue(handled, "the badge did not take the click")
        self.assertEqual(1, len(self.clicked),
                         "the versions dialog was not asked for")

    def test_the_same_click_does_NOTHING_in_LIST_mode(self):
        Position = QtWidgets.QStyleOptionViewItem.Position
        for decoration in (Position.Left, Position.Top):
            with self.subTest(decorationPosition=decoration.name):
                self.clicked.clear()
                option = _view_option(
                    self.view, list_mode=True, decoration=decoration)
                index = self.model.index(0, 0)
                handled = self.delegate.editorEvent(
                    self._release_on_the_badge(option), self.model,
                    option, index)
                self.assertFalse(
                    handled,
                    "a list row swallowed a click on a badge it never "
                    "drew")
                self.assertEqual(
                    [], self.clicked,
                    "clicking the empty lower-left corner of a list row "
                    "opened the Versions dialog")

    def test_the_TOOLTIP_stays_quiet_in_list_mode(self):
        """Through helpEvent, the real entry point - a hand call proves less."""
        Position = QtWidgets.QStyleOptionViewItem.Position
        for decoration in (Position.Left, Position.Top):
            with self.subTest(decorationPosition=decoration.name):
                option = _view_option(
                    self.view, list_mode=True, decoration=decoration)
                rect = self.delegate._badge_rect(
                    option.rect, True, delegates.LOWER_LEFT)
                event = QtGui.QHelpEvent(
                    QtCore.QEvent.Type.ToolTip, rect.center(),
                    self.view.mapToGlobal(rect.center()))
                self.assertFalse(
                    self.delegate.helpEvent(
                        event, self.view, option, self.model.index(0, 0)),
                    "a list row still answers the pointer where no "
                    "badge is")

    def test_one_question_decides_it(self):
        """Paint asks the view's viewMode; the hit-tests must ask the same."""
        for list_mode in (True, False):
            with self.subTest(list_mode=list_mode):
                self.assertEqual(
                    list_mode,
                    delegates.AssetItemDelegate._is_list(
                        self.delegate, _view_option(self.view, list_mode)))


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
        self.delegate = delegates.AssetItemDelegate(
            SUBTITLE_ROLE, favorite_role=FAVORITE_ROLE)
        self.delegate.set_badge_click("favourite", self.clicked.append)
        self.view.setItemDelegate(self.delegate)
        self.addCleanup(self.view.deleteLater)

    def _click_the_star(self, delegate, option):
        rect = delegate._badge_rect(
            option.rect,
            option.decorationPosition
            == QtWidgets.QStyleOptionViewItem.Position.Top,
            delegates.TOP_RIGHT)
        return delegate.editorEvent(
            _release(rect.center()), self.model, option,
            self.model.index(0, 0))

    def test_a_click_stars_a_tile_that_is_NOT_yet_a_favourite(self):
        """The new half: the badge answers while its role is FALSY - the resting star is a button, not an indicator that happens to be dim."""
        option = _view_option(self.view, list_mode=False)
        self.assertTrue(self._click_the_star(self.delegate, option),
                        "the resting star did not take the click")
        self.assertEqual(1, len(self.clicked),
                         "the favourite toggle was never asked for")

    def test_a_click_unstars_a_tile_that_IS_one(self):
        self.model.favourite = True
        option = _view_option(self.view, list_mode=False)
        self.assertTrue(self._click_the_star(self.delegate, option),
                        "the amber star did not take the click")
        self.assertEqual(1, len(self.clicked))

    def test_an_UNWIRED_delegate_offers_no_star_button(self):
        """The online grid: same role wired, no click - a click there must fall through to plain selection, because a button that does nothing is a lie."""
        bare = delegates.AssetItemDelegate(
            SUBTITLE_ROLE, favorite_role=FAVORITE_ROLE)
        self.view.setItemDelegate(bare)
        option = _view_option(self.view, list_mode=False)
        self.assertFalse(self._click_the_star(bare, option),
                         "a delegate with no click wired swallowed the "
                         "click anyway")

    def test_list_mode_offers_no_star_button(self):
        Position = QtWidgets.QStyleOptionViewItem.Position
        for decoration in (Position.Left, Position.Top):
            with self.subTest(decorationPosition=decoration.name):
                self.clicked.clear()
                option = _view_option(
                    self.view, list_mode=True, decoration=decoration)
                self.assertFalse(
                    self._click_the_star(self.delegate, option),
                    "a list row swallowed a click on a star it never "
                    "drew")
                self.assertEqual([], self.clicked)


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
        delegate = delegates.AssetItemDelegate(
            SUBTITLE_ROLE, notes_role=NOTES_ROLE)
        delegate.set_badge_click("comment", clicked.append)
        view.setItemDelegate(delegate)
        option = _view_option(view, list_mode=False)
        index = model.index(0, 0)
        rect = delegate._badge_rect(option.rect, True,
                                    delegates.LOWER_RIGHT)
        handled = delegate.editorEvent(
            _release(rect.center()), model, option, index)
        self.assertTrue(handled, "the comment badge swallowed nothing")
        self.assertEqual([index], clicked)

    def test_the_comment_art_pair_is_75_rest_100_hover(self):
        row = next(b for b in delegates.BADGES if b.name == "comment")
        self.assertEqual(
            "badge_comment_75", row.art,
            "the rest state is 75 percent - same as the rest of the "
            "family's buttons")
        self.assertEqual("badge_comment", row.hover_art,
                         "hover is the full-opacity mark")
        self.assertFalse(row.off_art,
                         "no badge on a commentless tile - the button "
                         "exists only where a comment does")

    def test_the_click_opens_the_pane_one_way(self):
        from amaze.tests import test_support
        panel = test_support.fixture_panel(test_support.class_scope(
            type(self)))
        panel.btn_notes.setChecked(False)
        index = panel.material_sorted_model.index(0, 0)
        panel._open_comments_from_badge(index)
        self.assertTrue(panel.btn_notes.isChecked(),
                        "the badge click did not open the pane")
        panel._open_comments_from_badge(index)
        self.assertTrue(panel.btn_notes.isChecked(),
                        "a second click CLOSED the pane - the badge "
                        "only ever opens")
        import amaze.panel.grid as grid_mod
        current = grid_mod.visible_view(panel).selectionModel() \
            .currentIndex()
        self.assertEqual(index.row(), current.row(),
                         "the clicked tile did not become the "
                         "selection, so the pane shows the wrong "
                         "comments")


if __name__ == "__main__":
    unittest.main()
