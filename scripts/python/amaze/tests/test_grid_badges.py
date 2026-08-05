"""A badge that is not DRAWN cannot be CLICKED.

BATCH 6 of the four-areas restructure. List mode stopped pretending to
be a grid on 2026-08-01: at list size a badge is 12px and its art
rasterises to a dark smudge, so the four badge facts became COLUMNS
there and the badges are painted in grid mode only.

The versions badge is the one interactive spot on a tile, and its
click and tooltip kept hit-testing in both modes - because they asked a
DIFFERENT question than the paint did. Paint asks the view's
`viewMode()`; the hit-tests asked `option.decorationPosition`, which is
a proxy for the same thing that nothing keeps in step. So in list mode
a click in the thumbnail's lower-left corner opened the Versions
dialog, over a badge that was never there, and hovering it claimed
"Click to select version".

One question, one answer: `_is_list(option)`.
"""

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
        """`decoration` is a PARAMETER because it must not matter. The
        hit-tests used to read `option.decorationPosition` as a proxy
        for the view mode; a fixture that sets the two to agree cannot
        tell a delegate that reads the wrong one (the sabotage round
        said exactly that), so the list-mode tests below run it both
        ways."""
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
        """A left-button release at the centre of where the badge sits
        (or would sit) - the same maths the delegate hit-tests with."""
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
        """The half that must keep working - a test for the list case
        alone would pass with the badge dead everywhere."""
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
        """It claimed 'Click to select version' over a badge that is not
        there - the same hit-test, so the same fix has to cover it.

        Through helpEvent, the real entry point: calling
        `versions_badge_at` with `mode_grid=False` by hand would only
        prove that False refuses, not that the tooltip path works out
        False for a list row."""
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
        """Paint asks the view's viewMode; so must the hit-tests. Two
        proxies for one fact is how they came apart."""
        for list_mode in (True, False):
            with self.subTest(list_mode=list_mode):
                self.assertEqual(
                    list_mode,
                    self.delegate._is_list(self._option(list_mode)))


if __name__ == "__main__":
    unittest.main()
