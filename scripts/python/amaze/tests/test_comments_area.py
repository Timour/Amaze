"""The Comments area: a context names its own subject, via `takes_comments` and `comment_subject`."""

import os
import sys
import types
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze import amazetheme  # noqa: E402
from amaze.panel import sections  # noqa: E402
from amaze.core import keyed_store, notes  # noqa: E402
from amaze.panel import notes_panel  # noqa: E402
from amaze.tests import test_support  # noqa: E402


class TheSubjectBelongsToTheContext(unittest.TestCase):

    def test_every_context_answers_the_question_itself(self):
        for name in ("AssetSection", "FileSection", "GradientSection",
                     "OnlineContext"):
            with self.subTest(context=name):
                context = getattr(sections, name)
                self.assertTrue(
                    hasattr(context, "comment_subject"),
                    "%s cannot say what its comment subject is, so the "
                    "panel has to know for it" % name)

    def test_a_context_that_takes_no_comments_has_no_subject(self):
        """The two questions must agree: a context whose chip is disabled cannot produce a subject."""
        self.assertFalse(sections.OnlineContext.takes_comments)
        self.assertIsNone(
            sections.OnlineContext.comment_subject(
                sections.OnlineContext.__new__(sections.OnlineContext), None))


class TheSubjectIsRightForEachContext(unittest.TestCase):
    """Driven through a real panel: a key with the right prefix, for the row actually selected."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _subject_for_last_row(self, key):
        """The subject for a row whose proxy position differs from its source position."""
        panel = self.panel
        panel.section_tabs.setChecked(key)
        QtWidgets.QApplication.processEvents()
        context = panel.active_section()
        proxy = panel.thumblist.model()
        self.assertIsNotNone(proxy, "the %s tab has no grid model" % key)
        self.assertGreater(
            proxy.rowCount(), 1,
            "the %s fixture has %d rows: with fewer than two, no filter "
            "can put a row at a proxy position that is not its source "
            "position, and this test cannot say anything"
            % (key, proxy.rowCount()))

        context.filter_text(proxy.index(proxy.rowCount() - 1, 0).data())
        self.addCleanup(self._clear_filter, key)
        QtWidgets.QApplication.processEvents()
        proxy = panel.thumblist.model()
        self.assertGreater(proxy.rowCount(), 0,
                           "the filter left no rows to select")
        index = proxy.index(0, 0)
        self.assertNotEqual(
            0, proxy.mapToSource(index).row(),
            "the surviving row is source row 0 as well, so an unmapped "
            "index would still read the right row and this test is not "
            "reproducing the conditions it exists for")

        panel.thumblist.setCurrentIndex(index)
        QtWidgets.QApplication.processEvents()
        return panel._notes_subject(), index

    def _clear_filter(self, key):
        self.panel.section_tabs.setChecked(key)
        QtWidgets.QApplication.processEvents()
        self.panel.active_section().filter_text("")
        QtWidgets.QApplication.processEvents()

    def test_a_material_subject_is_keyed_by_the_SELECTED_assets_id(self):
        subject, index = self._subject_for_last_row("material")
        self.assertIsNotNone(
            subject, "no subject for a material - the fixture library "
                     "has none, so this cannot test anything")
        model = self.panel.active_section().stack().model
        self.assertEqual(
            "material:%s" % index.data(model.IdRole), subject.key,
            "the comment key does not name the asset that is selected, "
            "so the pane writes onto a different tile's page")
        self.assertEqual(index.data(), subject.name)
        self.assertEqual(index.data(model.RendererLabelRole) or "", subject.type)

    def test_a_file_subject_is_keyed_by_the_SELECTED_rows_PATH(self):
        """`file_key(row)` reads the source model, so the index is mapped first; the header must agree."""
        subject, _index = self._subject_for_last_row("file")
        self.assertIsNotNone(
            subject, "no subject for a File row - the fixture location "
                     "is empty, so this cannot test anything")
        tail = subject.key[len("file:"):]    # `loc:<id>/<relative>`, so a moved location orphans no comment
        self.assertTrue(
            subject.key.startswith("file:") and tail.startswith("loc:")
            and "/" in tail,
            "a File row's comment key is %r - it must be 'file:' plus "
            "the location-keyed ident, which is what lets a comment "
            "follow the location wherever it moves" % subject.key)
        self.assertEqual(
            subject.name, os.path.basename(subject.key[len("file:"):]),
            "the key names one file and the header names another")

    def test_a_colour_subject_is_keyed_by_the_SELECTED_palettes_uid(self):
        """`tile_key(row)` is the same row-number read: the key's uid names the palette the header shows."""
        subject, _index = self._subject_for_last_row("gradient")
        self.assertIsNotNone(
            subject, "no subject for a palette - the fixture has none, "
                     "so this cannot test anything")
        uid = subject.key[len("gradient:"):]
        self.assertTrue(
            subject.key.startswith("gradient:") and uid,
            "a palette answered with %r - an EMPTY uid is one every "
            "palette would share" % subject.key)
        model = self.panel.gradient_model
        named = [model.entry(row).get("name", "")
                 for row in range(model.rowCount())
                 if model.tile_key(row) == uid]
        self.assertEqual(
            [subject.name], named,
            "the uid in the comment key belongs to a different palette "
            "than the one the header names")

    def test_a_selected_current_row_is_answered_without_listing_the_selection(self):
        """Every selection change asks this, so a wide selection must not cost a walk of it."""
        panel = self.panel
        panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        proxy = panel.thumblist.model()
        selection = panel.material_selection_model
        flags = QtCore.QItemSelectionModel.SelectionFlag
        current = proxy.index(proxy.rowCount() - 1, 0)
        selection.setCurrentIndex(current, flags.NoUpdate)
        selection.select(QtCore.QItemSelection(proxy.index(0, 0), current),
                         flags.ClearAndSelect | flags.Rows)
        self.addCleanup(selection.clearSelection)
        listed = []
        real = selection.selectedIndexes
        selection.selectedIndexes = lambda: (listed.append(1), real())[1]
        self.addCleanup(delattr, selection, "selectedIndexes")
        subject = panel._notes_subject()
        model = panel.active_section().stack().model
        self.assertEqual(
            "material:%s" % current.data(model.IdRole), subject.key,
            "the subject is not the current row, which is selected")
        self.assertEqual([], listed, "the lookup listed the whole selection "
                                     "to test one row")

    def test_the_online_world_has_no_subject_at_all(self):
        """An online record takes no comment, so the pane clears rather than keep the last subject."""
        panel = self.panel
        self.addCleanup(self._leave_online)
        panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        self.assertIsNotNone(self._subject_for_last_row("material")[0])

        panel.enter_online_world()
        QtWidgets.QApplication.processEvents()
        self.assertTrue(panel._is_online(), "not online, so this proves "
                                            "nothing")
        self.assertFalse(panel.active_section().takes_comments)    # BOTH halves, because they must agree: the chip with nothing selected, the subject with a selection
        self.assertIsNone(panel._notes_subject())

    def _leave_online(self):
        if self.panel._is_online():
            self.panel.leave_online_world()
        QtWidgets.QApplication.processEvents()


class NothingSelectedDimsThePane(unittest.TestCase):
    """Qt keeps the CURRENT tile when the selection empties, so the pane asks the selection instead."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.panel.resize(1400, 800)
        self.panel.show()
        self.addCleanup(self.panel.hide)
        self.panel.section_tabs.setChecked("material")
        self.panel.btn_notes.setChecked(True)
        QtWidgets.QApplication.processEvents()
        self.view = self.panel.thumblist
        self.assertGreater(self.view.model().rowCount(), 2,
                           "the fixture needs three tiles; row 0 is unnamed")

    def _click(self, pos, modifiers=QtCore.Qt.KeyboardModifier.NoModifier):
        """Press and release through the grid's own handlers, the door a real click goes through."""
        left = QtCore.Qt.MouseButton.LeftButton
        self.view.mousePressEvent(QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseButtonPress, QtCore.QPointF(pos),
            left, left, modifiers))
        self.view.mouseReleaseEvent(QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseButtonRelease, QtCore.QPointF(pos),
            left, QtCore.Qt.MouseButton.NoButton, modifiers))
        QtWidgets.QApplication.processEvents()

    def _tile(self, row):
        return self.view.visualRect(self.view.model().index(row, 0)).center()

    def _empty(self):
        rect = self.view.viewport().rect()
        for y in range(rect.bottom() - 2, 0, -20):
            for x in range(rect.right() - 2, 0, -20):
                if not self.view.indexAt(QtCore.QPoint(x, y)).isValid():
                    return QtCore.QPoint(x, y)
        self.fail("the grid has no empty space to click")

    def _key_of(self, row):
        return self.panel.active_section().comment_subject(
            self.view.model().index(row, 0)).key

    def _assert_dim(self):
        self.assertEqual([], self.panel.active_section().grid_selection(),
                         "the gesture left a selection")
        self.assertTrue(
            self.view.currentIndex().isValid(),
            "Qt dropped the current index as well, so this does not "
            "reproduce what a deselect leaves behind")
        self.assertIsNone(
            self.panel.notes_panel._key,
            "nothing is selected and the pane still shows the last tile")

    def test_an_empty_click_or_a_ctrl_click_off_the_one_tile_dims_the_pane(self):
        for name, where, modifier in (
                ("empty grid", self._empty, QtCore.Qt.KeyboardModifier.NoModifier),
                ("ctrl on the selected tile", lambda: self._tile(1),
                 QtCore.Qt.KeyboardModifier.ControlModifier)):
            with self.subTest(gesture=name):
                self._click(self._tile(1))
                self.assertEqual(self._key_of(1), self.panel.notes_panel._key)
                self._click(where(), modifier)
                self._assert_dim()

    def test_with_the_current_tile_deselected_the_pane_shows_a_selected_one(self):
        ctrl = QtCore.Qt.KeyboardModifier.ControlModifier
        self._click(self._tile(1))
        self._click(self._tile(2), ctrl)
        self.assertEqual(self._key_of(2), self.panel.notes_panel._key)
        self._click(self._tile(2), ctrl)
        self.assertEqual(2, self.view.currentIndex().row(),
                         "the deselected tile is not current, so this "
                         "proves nothing")
        self.assertEqual(self._key_of(1), self.panel.notes_panel._key,
                         "the pane shows a tile that is not selected")


class TheCommentsPaneHOLDSItsOwnWidth(unittest.TestCase):
    """One flexible pane, the grid; a side pane asks for a width and keeps it."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.panel.resize(1400, 800)
        self.panel.show()
        self.addCleanup(self.panel.hide)
        QtWidgets.QApplication.processEvents()

    def _sizes(self):
        splitter = self.panel.notes_panel.parentWidget()
        return {splitter.widget(i): size
                for i, size in enumerate(splitter.sizes())}

    def test_BOTH_side_panes_hold_their_width_the_same_way(self):
        from amaze.helpers import ui_helpers

        for name in ("cat_wrapper", "notes_panel"):
            with self.subTest(pane=name):
                self.assertIsInstance(
                    getattr(self.panel, name), ui_helpers.HeldPane,
                    "%s is not a held pane, so its width is kept by "
                    "something written just for it" % name)

    def test_opening_it_gives_it_the_REMEMBERED_width(self):
        self.panel.prefs.notes_panel_width = 320
        self.panel.btn_notes.setChecked(True)
        QtWidgets.QApplication.processEvents()
        self.assertEqual(320, self._sizes()[self.panel.notes_panel])

    def test_opening_it_takes_the_room_from_the_GRID(self):
        """Not from the sidebar - the grid is the one pane that flexes."""
        sidebar = self.panel.cat_wrapper
        before = self._sizes()[sidebar]
        self.panel.btn_notes.setChecked(True)
        QtWidgets.QApplication.processEvents()
        self.assertEqual(
            before, self._sizes()[sidebar],
            "opening Comments resized the SIDEBAR, which holds its own "
            "width")



class TheHeaderFollowsTheAssetItNames(unittest.TestCase):
    """A rename keeps the comment key, yet the header must show the new name."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.prefs = test_support.fixture_prefs(self)
        self.pane = notes_panel.NotesPanel(self.prefs)
        self.addCleanup(self.pane.deleteLater)
        self.pane.set_subject(sections.CommentSubject("material:asset-1", "Old Name", "Karma"))

    def test_a_renamed_asset_shows_its_NEW_name(self):
        self.pane.set_subject(sections.CommentSubject("material:asset-1", "New Name", "Karma"))
        self.assertEqual("New Name", self.pane.name_label.text())

    def test_an_edit_IN_PROGRESS_survives_the_header_update(self):
        """`set_subject` runs on every click, so a rename moves the header but never reloads the page."""
        self.pane.text_edit.setPlainText("half a sentence")
        self.pane.set_subject(sections.CommentSubject("material:asset-1", "New Name", "Karma"))
        self.assertEqual("half a sentence",
                         self.pane.text_edit.toPlainText())


class APendingEditIsNotLostOnTheWayOUT(unittest.TestCase):
    """Typed text waits 600ms for the debounce, so every way the pane goes away writes it first."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.prefs = test_support.fixture_prefs(self)
        self.pane = notes_panel.NotesPanel(self.prefs)
        self.addCleanup(self.pane.deleteLater)

    def _pending_edit(self, key="material:asset-1", shown=True):
        if shown:
            self.pane.show()    # a hide event only arrives at a widget that was showing
            QtWidgets.QApplication.processEvents()
        self.pane.set_subject(sections.CommentSubject(key, "Rusty", "Karma"))
        self.pane.text_edit.setPlainText("typed but not yet saved")
        self.assertTrue(
            self.pane._save_timer.isActive(),
            "the edit did not start the debounce, so nothing is pending "
            "and this test cannot say anything")
        return key

    def _stored(self, key):
        return notes.note_for(self.prefs, key).get("items", [])

    def test_hiding_the_pane_writes_it(self):
        key = self._pending_edit()
        self.pane.hide()
        QtWidgets.QApplication.processEvents()
        self.assertTrue(self._stored(key), "the page is empty on disk")

    def test_CLOSING_a_pane_that_was_never_SHOWN_writes_it(self):
        """Without the show, a close delivers no hide event, so this tests the close path alone."""
        key = self._pending_edit(shown=False)
        self.pane.close()
        QtWidgets.QApplication.processEvents()
        self.assertTrue(self._stored(key), "the page is empty on disk")

    def test_the_pane_is_wired_to_the_APPLICATION_quitting(self):
        """Houdini quitting sends no widget event, so `aboutToQuit` reaches `flush`; checked, not emitted."""
        app = QtWidgets.QApplication.instance()
        was_connected = app.aboutToQuit.disconnect(self.pane.flush)    # disconnect() returns False for a connection never made, it does not raise
        if was_connected:
            app.aboutToQuit.connect(self.pane.flush)
        self.assertTrue(
            was_connected,
            "the Comments pane does not flush when the application "
            "quits - the last 600ms of typing goes with the session")

    def test_a_pane_with_nothing_pending_writes_nothing(self):
        """`flush()` runs on every teardown and subject switch, so it writes nothing when nothing changed."""
        self.pane.set_subject(sections.CommentSubject("material:asset-2", "Rusty", "Karma"))
        before = self._stored("material:asset-2")
        self.pane.close()
        self.assertEqual(before, self._stored("material:asset-2"))


class ALibrarySwitchLeavesTheNoteWhereItWasTyped(unittest.TestCase):
    """A page is written to the library it was read from, and a switch leaves nothing selected."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.panel.resize(1400, 800)
        self.panel.show()
        self.addCleanup(self.panel.hide)
        self.addCleanup(keyed_store.release)
        self.panel.section_tabs.setChecked("material")
        self.panel.btn_notes.setChecked(True)
        QtWidgets.QApplication.processEvents()

    def _pick_tile(self, row):
        view = self.panel.thumblist
        pos = QtCore.QPointF(view.visualRect(view.model().index(row, 0)).center())
        left = QtCore.Qt.MouseButton.LeftButton
        plain = QtCore.Qt.KeyboardModifier.NoModifier
        view.mousePressEvent(QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseButtonPress, pos, left, left, plain))
        view.mouseReleaseEvent(QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseButtonRelease, pos, left,
            QtCore.Qt.MouseButton.NoButton, plain))
        QtWidgets.QApplication.processEvents()

    def _switch_library(self):
        """Preferences' own door: another library picked, with a user, and Apply."""
        other = test_support.seeded_library(self)
        self.assertTrue(test_support.apply_library(self, self.panel, other))
        QtWidgets.QApplication.processEvents()
        return other

    def _typed_in(self, library, key):
        keyed_store.release()    # the page as it is ON DISK, not as a cached table holds it
        page = notes.note_for(types.SimpleNamespace(dir=library), key)
        return [item.get("text", "") for item in page.get("items", [])]

    def test_a_pending_edit_is_written_to_the_library_it_was_typed_in(self):
        pane = self.panel.notes_panel
        self._pick_tile(1)
        key = pane._key
        self.assertIsNotNone(key, "no tile picked, so nothing can be typed")
        old = self.panel.prefs.dir
        pane.text_edit.setPlainText("typed before the switch")
        self.assertTrue(pane._save_timer.isActive(),
                        "nothing is pending, so this test cannot say anything")

        new = self._switch_library()
        self.assertNotEqual(old, self.panel.prefs.dir)
        pane.flush()    # the debounce firing after the switch

        self.assertIn("typed before the switch", self._typed_in(old, key),
                      "the edit never reached the library it was typed in")
        self.assertNotIn("typed before the switch", self._typed_in(new, key),
                         "the edit was written into the library switched to")

    def test_after_a_switch_the_pane_shows_nothing_selected(self):
        pane = self.panel.notes_panel
        self._pick_tile(1)
        self.assertIsNotNone(pane._key, "no tile picked, so this proves nothing")

        self._switch_library()

        self.assertIsNone(pane._key,
                          "the pane still shows the previous library's asset")
        self.assertFalse(pane.text_edit.isEnabled(),
                         "the pane still takes typing for an asset not on screen")
        self.assertEqual(amazetheme.COMMENT_DIM_NAME, pane.name_label.text())


class ThePANEL_BEING_DESTROYED_writesAPendingEdit(unittest.TestCase):
    """Deleting a parent sends its children no hide event, and a Houdini pane tab closes by deletion."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)

    def test_deleting_the_panel_flushes_the_pane_first(self):
        pane = self.panel.notes_panel
        prefs = self.panel.prefs    # held now: after the delete, reading anything off the panel is a use-after-free
        pane.set_subject(sections.CommentSubject("material:asset-9", "Rusty", "Karma"))
        pane.text_edit.setPlainText("typed as the tab closed")
        self.assertTrue(pane._save_timer.isActive(),
                        "nothing pending, so this test cannot say "
                        "anything")

        test_support.stop_panel_workers(self.panel)
        self.panel.deleteLater()
        QtWidgets.QApplication.sendPostedEvents(
            None, QtCore.QEvent.Type.DeferredDelete)    # processEvents() never delivers DeferredDelete; sending it does what a tab close does
        QtWidgets.QApplication.processEvents()

        self.assertTrue(
            notes.note_for(prefs, "material:asset-9").get("items", []),
            "the page is empty on disk - the edit died with the tab")


if __name__ == "__main__":
    unittest.main()
