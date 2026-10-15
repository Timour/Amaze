"""The Comments area: a context says what its own subject is - `takes_comments` answers CAN this context ever carry one (the toolbar chip, with nothing selected), `comment_subject(index)` answers what the subject is RIGHT NOW, and only a context can map its own index."""

import ast
import json
import os
import sys
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze import amazetheme  # noqa: E402
from amaze.panel import sections  # noqa: E402
from amaze.core import keyed_store, notes  # noqa: E402
from amaze.panel import notes_panel, sections  # noqa: E402
from amaze.tests import test_support  # noqa: E402

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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

    def test_the_panel_no_longer_branches_on_which_section(self):
        """The three branches were the defect's shape: each mapped an index through one section's proxy and read one section's roles, in a method that serves all of them."""
        with open(os.path.join(PACKAGE, "panel", "panel.py"),
                  encoding="utf-8") as handle:
            source = handle.read()
        tree = ast.parse(source)
        subject = [n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef)
                   and n.name == "_notes_subject"]
        self.assertEqual(1, len(subject), "no _notes_subject to check")
        literals = {n.value for n in ast.walk(subject[0])
                    if isinstance(n, ast.Constant)
                    and isinstance(n.value, str)}
        for key in ("file", "material", "cop", "code", "gradient"):
            self.assertNotIn(
                key, literals,
                "the Comments subject lookup still names the %r section, "
                "so it carries knowledge that belongs on that context"
                % key)

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
        """The subject for a row whose PROXY position differs from its source position (the last row filtered to proxy row 0) - with the two orders agreeing, an unmapped index looks correct and the test cannot fail."""
        panel = self.panel
        panel.section_tabs.setChecked(key)
        QtWidgets.QApplication.processEvents()
        context = panel._section()
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
        self.panel._section().filter_text("")
        QtWidgets.QApplication.processEvents()

    def test_a_material_subject_is_keyed_by_the_SELECTED_assets_id(self):
        subject, index = self._subject_for_last_row("material")
        self.assertIsNotNone(
            subject, "no subject for a material - the fixture library "
                     "has none, so this cannot test anything")
        model = self.panel._section().stack().model
        self.assertEqual(
            "material:%s" % index.data(model.IdRole), subject.key,
            "the comment key does not name the asset that is selected, "
            "so the pane writes onto a different tile's page")
        self.assertEqual(index.data(), subject.name)
        self.assertEqual(index.data(model.RendererLabelRole) or "", subject.type)

    def test_a_file_subject_is_keyed_by_the_SELECTED_rows_PATH(self):
        """`file_key(row)` is a row-number read against the SOURCE model, so the index has to be mapped first - the header's name comes from the index instead, and the two disagree the moment the mapping is dropped."""
        subject, _index = self._subject_for_last_row("file")
        self.assertIsNotNone(
            subject, "no subject for a File row - the fixture location "
                     "is empty, so this cannot test anything")
        tail = subject.key[len("file:"):]    # the location-keyed ident, `loc:<id>/<relative>` - a moved location orphans no comment, and one file gets one key however its location is spelled
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
        """`note_uid(row)` is the same row-number read, checked the same way: the uid is looked up in the source model, and the name stored against it must be the name the header shows."""
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
                 if model.note_uid(row) == uid]
        self.assertEqual(
            [subject.name], named,
            "the uid in the comment key belongs to a different palette "
            "than the one the header names")

    def test_the_online_world_has_no_subject_at_all(self):
        """An online record is not a library asset: nothing to write a comment against, and the pane must clear rather than keep pointing at whatever was selected before."""
        panel = self.panel
        self.addCleanup(self._leave_online)
        panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        self.assertIsNotNone(self._subject_for_last_row("material")[0])

        panel.enter_online_world()
        QtWidgets.QApplication.processEvents()
        self.assertTrue(panel._is_online(), "not online, so this proves "
                                            "nothing")
        self.assertFalse(panel._section().takes_comments)    # BOTH halves, because they must agree: the chip with nothing selected, the subject with a selection
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
        return self.panel._section().comment_subject(
            self.view.model().index(row, 0)).key

    def _assert_dim(self):
        self.assertEqual([], self.panel._section().grid_selection(),
                         "the gesture left a selection")
        self.assertTrue(
            self.view.currentIndex().isValid(),
            "Qt dropped the current index as well, so this does not "
            "reproduce what a deselect leaves behind")
        self.assertIsNone(
            self.panel.notes_panel._key,
            "nothing is selected and the pane still shows the last tile")

    def test_a_click_on_empty_grid_dims_the_pane(self):
        self._click(self._tile(1))
        self.assertEqual(self._key_of(1), self.panel.notes_panel._key)
        self._click(self._empty())
        self._assert_dim()

    def test_a_ctrl_click_on_the_one_selected_tile_dims_the_pane(self):
        self._click(self._tile(1))
        self.assertEqual(self._key_of(1), self.panel.notes_panel._key)
        self._click(self._tile(1), QtCore.Qt.KeyboardModifier.ControlModifier)
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
    """The construction's law: ONE flexible pane (the grid), and a side pane asks for a width and keeps it - measured at panel widths 1400px down to 620px, the splitter honours the sizeHint before `shown` ever fires."""

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

    def test_the_panel_does_no_splitter_arithmetic_for_it(self):
        with open(os.path.join(PACKAGE, "panel", "panel.py"),
                  encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn(
            "_apply_notes_width", source,
            "the panel still computes the Comments pane's width by "
            "hand, which the pane itself already answers")


class TheHeaderFollowsTheAssetItNames(unittest.TestCase):
    """A comment is keyed by IDENTITY, which a rename does not change - so the pane is pointed at the same key it already holds, the one case `set_subject` returns early on, and the header kept the OLD name for as long as the pane stayed open."""

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
        """set_subject is called on every click, and reloading the stored page there would throw away whatever is being typed - the header may follow a rename; the PAGE must not be reloaded with it."""
        self.pane.text_edit.setPlainText("half a sentence")
        self.pane.set_subject(sections.CommentSubject("material:asset-1", "New Name", "Karma"))
        self.assertEqual("half a sentence",
                         self.pane.text_edit.toPlainText())


class APendingEditIsNotLostOnTheWayOUT(unittest.TestCase):
    """600ms of typed text lives only in the widget until the debounce fires - every way the pane can go away has to write it first."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.prefs = test_support.fixture_prefs(self)
        self.pane = notes_panel.NotesPanel(self.prefs)
        self.addCleanup(self.pane.deleteLater)

    def _pending_edit(self, key="material:asset-1", shown=True):
        if shown:
            self.pane.show()    # a hide event only arrives at a widget that was showing; without this hide() is a no-op and the test passes for no reason
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
        """Deliberately without the show: a close then delivers no hide event, so hideEvent is not the thing being tested here."""
        key = self._pending_edit(shown=False)
        self.pane.close()
        QtWidgets.QApplication.processEvents()
        self.assertTrue(self._stored(key), "the page is empty on disk")

    def test_the_pane_is_wired_to_the_APPLICATION_quitting(self):
        """Houdini shutting down reaches no widget event of ours, so the pane rides `aboutToQuit` - checked by DISCONNECTING rather than emitting, because a real `aboutToQuit` in this one-process suite would shut the thumbnail engine down under every test that follows; that flush() writes is pinned above, what is left is that quitting reaches it."""
        app = QtWidgets.QApplication.instance()
        was_connected = app.aboutToQuit.disconnect(self.pane.flush)    # the RETURN VALUE is the answer - disconnect() warns and returns False for a connection never made, it does not raise (probed), so a try/except would pass either way
        if was_connected:
            app.aboutToQuit.connect(self.pane.flush)
        self.assertTrue(
            was_connected,
            "the Comments pane does not flush when the application "
            "quits - the last 600ms of typing goes with the session")

    def test_a_pane_with_nothing_pending_writes_nothing(self):
        """flush() runs on every teardown path AND every subject switch, so it has to be free when there is nothing to write - otherwise every click rewrites a page."""
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
        """Set Library's own door, the folder picker answering the way a real pick saves."""
        other = test_support.fresh_library(self)
        settings = os.path.join(self.panel.prefs.path, "settings.json")
        with open(settings, encoding="utf-8") as handle:
            data = json.load(handle)
        data["directory"] = other
        with open(settings, "w", encoding="utf-8") as handle:
            json.dump(data, handle)

        def picked():
            self.panel.prefs.dir = other
            return True

        with mock.patch.object(self.panel.prefs, "get_dir_from_user", picked):
            self.panel.set_library()
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
    """The teardown a child cannot see for itself - measured: closing a window sends its children hide events, deleting a parent sends them NOTHING, and deletion is how a Houdini pane tab goes away. Its own panel, because the test ends by destroying it."""

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
            None, QtCore.QEvent.Type.DeferredDelete)    # processEvents() alone never delivers this: Qt holds DeferredDelete until the posting event loop returns, and a test has no such loop - sending it explicitly reproduces what Houdini's loop does when the tab closes
        QtWidgets.QApplication.processEvents()

        self.assertTrue(
            notes.note_for(prefs, "material:asset-9").get("items", []),
            "the page is empty on disk - the edit died with the tab")


if __name__ == "__main__":
    unittest.main()
