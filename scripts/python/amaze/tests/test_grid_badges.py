"""A badge that is not DRAWN cannot be CLICKED - list mode paints no badges."""

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

    TILE = 128

    def setUp(self):
        self.clicked = []
        self.model = _Rows()
        self.view = QtWidgets.QListView()
        self.view.setModel(self.model)
        self.delegate = delegates.AssetItemDelegate(
            SUBTITLE_ROLE, versions_role=VERSIONS_ROLE)
        self.delegate.set_versions_click(self.clicked.append)
        self.view.setItemDelegate(self.delegate)
        self.addCleanup(self.view.deleteLater)

    def _option(self, list_mode, decoration=None):
        """`decoration` must not matter - the list tests run it both ways."""
        self.view.setViewMode(
            QtWidgets.QListView.ViewMode.ListMode if list_mode
            else QtWidgets.QListView.ViewMode.IconMode)
        option = QtWidgets.QStyleOptionViewItem()
        option.widget = self.view
        option.rect = QtCore.QRect(0, 0, self.TILE, self.TILE)
        option.decorationPosition = decoration or (
            QtWidgets.QStyleOptionViewItem.Position.Left if list_mode
            else QtWidgets.QStyleOptionViewItem.Position.Top)
        return option

    def _release_on_the_badge(self, option):
        """A left-button release at the centre of the badge's rect."""
        rect = self.delegate._versions_badge_rect(
            option.rect,
            option.decorationPosition
            == QtWidgets.QStyleOptionViewItem.Position.Top)
        point = QtCore.QPointF(rect.center())
        return QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseButtonRelease, point,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier)

    def test_a_click_on_the_badge_opens_versions_in_GRID_mode(self):
        """The half that must keep working - list-only coverage passes dead."""
        option = self._option(list_mode=False)
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
                option = self._option(list_mode=True, decoration=decoration)
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
                option = self._option(list_mode=True, decoration=decoration)
                rect = self.delegate._versions_badge_rect(option.rect, True)
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
                    self.delegate._is_list(self._option(list_mode)))


if __name__ == "__main__":
    unittest.main()
