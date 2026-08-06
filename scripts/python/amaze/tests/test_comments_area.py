"""The Comments area: a context says what its own subject is.

BATCH 9 of the four-areas restructure, and the last of them.

`_notes_subject` branched on `section.key` three ways - File, the three
Asset sections, and Color - with each branch mapping an index through
that section's own proxy and reading that section's own roles. Per-
section knowledge sitting in the panel, which is the same shape batch 4
collapsed for activation and batch 8 collapsed for the toolbar.

Comments is the FOURTH AREA, not an exception - the roadmap's words,
and this is what makes it true in code.

Two questions, deliberately kept apart:

* `takes_comments` - CAN this context ever carry a comment? The toolbar
  chip needs that answer with nothing selected.
* `comment_subject(index)` - what is the subject RIGHT NOW? Needs a
  selection, and only a context can map its own index.
"""

import ast
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.panel import sections  # noqa: E402
from amaze.core import notes  # noqa: E402
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
        """The three branches were the defect's shape, not a defect in
        themselves: each mapped an index through one section's proxy and
        read one section's roles, in a method that serves all of them."""
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
        """The two questions must agree: a context whose chip is
        disabled cannot produce a subject."""
        self.assertFalse(sections.OnlineContext.takes_comments)
        self.assertIsNone(
            sections.OnlineContext.comment_subject(
                sections.OnlineContext.__new__(sections.OnlineContext), None))


class TheSubjectIsRightForEachContext(unittest.TestCase):
    """Driven through a real panel: a key with the right prefix, for the
    row actually selected."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _subject_for_last_row(self, key):
        """The subject for a row whose PROXY position is not its source
        position - the only conditions under which a subject built from
        an unmapped index looks wrong.

        Reached by typing the last row's name into the filter box, which
        is what a user does: the row that survives is at proxy row 0 and
        somewhere else entirely in the source model. Without this the
        two orders agree, every mapping looks correct, and the test
        cannot fail (the first version of it could not - the sabotage
        round said so)."""
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
        # The header shows ONE category - the first, which is the one
        # the sidebar files the asset under.
        held = index.data(model.CategoryRole)
        first = (held[0] if isinstance(held, (list, tuple)) and held
                 else str(held or ""))
        self.assertEqual(str(first), subject.category,
                         "the header names a category the asset is not "
                         "filed under first")

    def test_a_file_subject_is_keyed_by_the_SELECTED_rows_PATH(self):
        """`file_key(row)` is a row-number read against the SOURCE
        model, so the index has to be mapped first. The name in the
        header comes from the index instead - so the two disagree the
        moment the mapping is dropped, and that is what this compares."""
        subject, _index = self._subject_for_last_row("file")
        self.assertIsNotNone(
            subject, "no subject for a File row - the fixture location "
                     "is empty, so this cannot test anything")
        # The path after the prefix is CANONICAL (file_key, 2026-08-06)
        # - one spelling per file, absolute, idempotent under
        # canonical_path_key. Asserting a leading slash encoded the
        # macOS spelling; asserting os-native encoded the Windows one.
        from amaze.helpers import hostos
        tail = subject.key[len("file:"):]
        self.assertTrue(
            subject.key.startswith("file:") and os.path.isabs(tail)
            and hostos.canonical_path_key(tail) == tail,
            "a File row's comment key is %r - it must be 'file:' plus "
            "the one canonical absolute path, which is what makes a "
            "comment come back when the location is removed and "
            "registered again, however the location is spelled"
            % subject.key)
        self.assertEqual(
            subject.name, os.path.basename(subject.key[len("file:"):]),
            "the key names one file and the header names another")

    def test_a_colour_subject_is_keyed_by_the_SELECTED_palettes_uid(self):
        """`note_uid(row)` is the same row-number read, checked the same
        way: the uid is looked up in the source model here, and the name
        stored against it must be the name the header shows."""
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

    def test_every_subject_carries_the_six_things_the_pane_paints(self):
        for key in ("material", "file", "gradient"):
            with self.subTest(section=key):
                subject, _index = self._subject_for_last_row(key)
                self.assertIsNotNone(subject)
                self.assertEqual(
                    6, len(subject),
                    "%s answered with %d fields; the Comments header "
                    "paints six" % (key, len(subject)))

    def test_the_online_world_has_no_subject_at_all(self):
        """An online record is not a library asset: there is nothing to
        write a comment against, and the pane must clear rather than
        keep pointing at whatever was selected before."""
        panel = self.panel
        self.addCleanup(self._leave_online)
        panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        self.assertIsNotNone(self._subject_for_last_row("material")[0])

        panel.enter_online_world()
        QtWidgets.QApplication.processEvents()
        self.assertTrue(panel._is_online(), "not online, so this proves "
                                            "nothing")
        # BOTH halves, because they must agree: the chip the toolbar
        # reads with nothing selected, and the subject with a selection.
        self.assertFalse(panel._section().takes_comments)
        self.assertIsNone(panel._notes_subject())

    def _leave_online(self):
        if self.panel._is_online():
            self.panel.leave_online_world()
        QtWidgets.QApplication.processEvents()


class TheCommentsPaneHOLDSItsOwnWidth(unittest.TestCase):
    """The construction's law is one flexible pane (the grid); a side
    pane asks for a width and keeps it. The sidebar has said so through
    a shared widget since it was built - the Comments pane said it
    through 50 lines of splitter arithmetic on the panel instead.

    Measured before removing that arithmetic: with it disconnected, the
    pane came up at exactly the same width in every case, at panel
    widths from 1400px down to 620px. By the time its `shown` signal
    fires the splitter has already honoured the sizeHint, so the method
    was recomputing what was already true - and every guard inside it
    was unreachable."""

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
        """Not from the sidebar - the defect the old arithmetic was
        written for. The grid is the one pane that flexes."""
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


class _Stack:
    """A stand-in for the curated-library stack, holding ONE row.

    Written as a stub deliberately, and only for the one thing a
    fixture asset cannot show: an asset filed under SEVERAL categories.
    The header has room for one, and which one is a choice inside
    comment_subject - so the list is the input and the choice is what
    is under test."""

    IdRole = 1
    CategoryRole = 2
    CategoryColorRole = 3
    RendererLabelRole = 4
    NOTES_SECTION = "material"

    def __init__(self, categories):
        self._fields = {
            QtCore.Qt.ItemDataRole.DisplayRole: "Rusty Metal",
            self.IdRole: "asset-1",
            self.CategoryRole: categories,
            self.CategoryColorRole: "#ff8000",
            self.RendererLabelRole: "Karma",
        }

    # -- as the model ---------------------------------------------------
    def data(self, role):
        return self._fields.get(role)

    # -- as the proxy ---------------------------------------------------
    def mapToSource(self, _index):
        return self

    # -- as the source index --------------------------------------------
    def isValid(self):
        return True


class AnAssetFiledUnderSeveralCategories(unittest.TestCase):

    def _subject_for(self, categories):
        stack = _Stack(categories)
        section = sections.MaterialSection.__new__(sections.MaterialSection)
        section.stack = lambda: sections.AssetStack(
            model=stack, proxy=stack, selection=None, categories=None)
        return section.comment_subject(None)

    def test_the_header_shows_the_FIRST_one(self):
        """The first is the one the sidebar files it under, so it is the
        one the header has to agree with."""
        subject = self._subject_for(["Metal", "Wood", "Fabric"])
        self.assertEqual("Metal", subject.category)

    def test_an_asset_under_none_shows_no_category(self):
        self.assertEqual("", self._subject_for([]).category)

    def test_a_single_name_is_taken_as_it_stands(self):
        """Older rows hold a plain string rather than a list."""
        self.assertEqual("Metal", self._subject_for("Metal").category)


class TheLocationBehindAFileRow(unittest.TestCase):
    """`location_for` moved out of the panel with the File branch. It
    is what puts a location's NAME and COLOUR in the Comments header,
    and the header is the only place a file row shows either.

    Built on the real FileFolders model rather than a stub, because the
    two answers it gives - the custom display name and the Set Color
    colour - are that model's own, and a stub would test the stub."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        # A location registered INSIDE another one. Never the real
        # photo archive: both are fresh temporary directories.
        self.outer = test_support.fresh_files_folder(self)
        self.inner = os.path.join(self.outer, "inner")
        os.makedirs(self.inner, exist_ok=True)
        self.section = self._section_registering(self.outer, self.inner)

    def _section_registering(self, *paths):
        """A File section whose locations were registered in the order
        given. The ORDER is a test parameter on purpose: a rule of
        "first one that covers it" and a rule of "last one that covers
        it" each look right under one order and wrong under the other,
        and neither is longest-prefix."""
        prefs = test_support.fixture_prefs(self)
        for path in paths:
            prefs.add_file_folder(path)
        prefs.set_file_folder_color(self.inner, "#4af2a1")

        from amaze.core import file_library

        folders = file_library.FileFolders(preferences=prefs)
        return sections.FileSection(_PanelStub(prefs, folders))

    def test_the_innermost_registered_location_wins(self):
        """A file under both answers to the NEARER one - otherwise the
        header names a location the user did not put it in, and paints
        that location's colour beside it."""
        for order in ((self.outer, self.inner), (self.inner, self.outer)):
            with self.subTest(registered=("outer first"
                                          if order[0] == self.outer
                                          else "inner first")):
                section = self._section_registering(*order)
                location, label, colour = section.location_for(
                    os.path.join(self.inner, "shot.exr"))
                self.assertEqual(
                    self.inner, location,
                    "a file inside the nested location answered with %r"
                    % location)
                self.assertEqual("#4af2a1", colour)
                self.assertTrue(label, "the location has no label to show")

    def test_a_file_under_no_registered_location_has_none(self):
        location, label, colour = self.section.location_for(
            "/somewhere/else/shot.exr")
        self.assertEqual(("", "", ""), (location, label, colour))

    def test_a_SIBLING_whose_name_merely_extends_it_is_not_inside_it(self):
        """`/plates` does not contain `/plates_backup/shot.exr`. A
        prefix compared without its separator says it does, and the
        header then names a location the file is not in - the same
        boundary bug the notes store had for `retire_prefix`."""
        # rstrip BOTH separators: fresh_files_folder returns the path
        # with a trailing os.sep, and on Windows rstrip("/") leaves the
        # backslash - the probe then lands INSIDE the location, in a
        # subfolder literally named `_backup`, and the product's correct
        # answer read as the boundary bug this test exists to catch.
        location, label, colour = self.section.location_for(
            self.outer.rstrip("/\\") + "_backup/shot.exr")
        self.assertEqual(
            ("", "", ""), (location, label, colour),
            "a file in a SIBLING location answered with %r" % location)

    def test_the_label_follows_a_RENAMED_location(self):
        """The name a location was given is the model's answer, not the
        basename - so the header has to ask the model."""
        self.section.panel.prefs.set_file_folder_name(self.outer, "Plates")
        _location, label, _colour = self.section.location_for(
            os.path.join(self.outer, "shot.exr"))
        self.assertEqual("Plates", label)


class TheHeaderFollowsTheAssetItNames(unittest.TestCase):
    """A comment is keyed by IDENTITY - an id, a path, a uid - and a
    rename changes none of those. So the pane is pointed at the same
    key it already holds, which is the one case `set_subject` returns
    early on, and the header kept the OLD name for as long as the pane
    stayed open."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.prefs = test_support.fixture_prefs(self)
        self.pane = notes_panel.NotesPanel(self.prefs)
        self.addCleanup(self.pane.deleteLater)
        self.pane.set_subject(sections.CommentSubject("material:asset-1", "material", "Old Name",
                              "Karma", "Metal", "#ff8000"))

    def test_a_renamed_asset_shows_its_NEW_name(self):
        self.pane.set_subject(sections.CommentSubject("material:asset-1", "material", "New Name",
                              "Karma", "Metal", "#ff8000"))
        self.assertEqual("New Name", self.pane.name_label.text())

    def test_a_recategorised_asset_shows_its_NEW_category(self):
        self.pane.set_subject(sections.CommentSubject("material:asset-1", "material", "Old Name",
                              "Karma", "Wood", "#4af2a1"))
        self.assertIn("Wood", self.pane.section_label.text())

    def test_an_edit_IN_PROGRESS_survives_the_header_update(self):
        """The reason set_subject returns early on a same-key call: it
        is called on every click, and reloading the stored page there
        would throw away whatever is being typed. The header may follow
        a rename; the PAGE must not be reloaded with it."""
        self.pane.text_edit.setPlainText("half a sentence")
        self.pane.set_subject(sections.CommentSubject("material:asset-1", "material", "New Name",
                              "Karma", "Metal", "#ff8000"))
        self.assertEqual("half a sentence",
                         self.pane.text_edit.toPlainText())


class APendingEditIsNotLostOnTheWayOUT(unittest.TestCase):
    """600ms of typed text lives only in the widget until the debounce
    fires. Every way the pane can go away has to write it first."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.prefs = test_support.fixture_prefs(self)
        self.pane = notes_panel.NotesPanel(self.prefs)
        self.addCleanup(self.pane.deleteLater)

    def _pending_edit(self, key="material:asset-1", shown=True):
        if shown:
            # A hide event only arrives at a widget that was showing;
            # without this the pane is hidden already and hide() is a
            # no-op, which is a test that passes for no reason.
            self.pane.show()
            QtWidgets.QApplication.processEvents()
        self.pane.set_subject(sections.CommentSubject(key, "material", "Rusty", "Karma"))
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
        """Deliberately without the show: a close then delivers no hide
        event, so hideEvent is not the thing being tested here."""
        key = self._pending_edit(shown=False)
        self.pane.close()
        QtWidgets.QApplication.processEvents()
        self.assertTrue(self._stored(key), "the page is empty on disk")

    def test_the_pane_is_wired_to_the_APPLICATION_quitting(self):
        """Houdini shutting down reaches no widget event of ours, so
        the pane rides `aboutToQuit` - the wiki's rule for the
        thumbnail engine, and the same rule for unsaved typing.

        Checked by DISCONNECTING rather than by emitting: this suite
        runs every module in one hython process, and a real
        `aboutToQuit` would shut the thumbnail engine down under every
        test that follows. That flush() actually writes is pinned by
        the two tests above; what is left to pin is that quitting
        reaches it.

        The RETURN VALUE is the answer - PySide's disconnect() warns and
        returns False for a connection that was never made, it does not
        raise (probed), so a try/except here would pass either way."""
        app = QtWidgets.QApplication.instance()
        was_connected = app.aboutToQuit.disconnect(self.pane.flush)
        if was_connected:
            app.aboutToQuit.connect(self.pane.flush)
        self.assertTrue(
            was_connected,
            "the Comments pane does not flush when the application "
            "quits - the last 600ms of typing goes with the session")

    def test_a_pane_with_nothing_pending_writes_nothing(self):
        """flush() is called on every teardown path AND on every subject
        switch, so it has to be free when there is nothing to write -
        otherwise every click rewrites a page."""
        self.pane.set_subject(sections.CommentSubject("material:asset-2", "material", "Rusty",
                              "Karma"))
        before = self._stored("material:asset-2")
        self.pane.close()
        self.assertEqual(before, self._stored("material:asset-2"))


class ThePANEL_BEING_DESTROYED_writesAPendingEdit(unittest.TestCase):
    """The teardown a child widget cannot see for itself. Measured:
    hiding or closing a window sends hide events to its children, but
    deleting a parent sends them nothing - and deletion is how a
    Houdini pane tab goes away.

    Its own panel, because the test ends by destroying it."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)

    def test_deleting_the_panel_flushes_the_pane_first(self):
        pane = self.panel.notes_panel
        # Held now: after the delete, reading anything off the panel is
        # a use-after-free.
        prefs = self.panel.prefs
        pane.set_subject(sections.CommentSubject("material:asset-9", "material", "Rusty", "Karma"))
        pane.text_edit.setPlainText("typed as the tab closed")
        self.assertTrue(pane._save_timer.isActive(),
                        "nothing pending, so this test cannot say "
                        "anything")

        test_support.stop_panel_workers(self.panel)
        self.panel.deleteLater()
        # processEvents() alone never delivers this one: Qt holds
        # DeferredDelete until the event loop that posted it returns,
        # and a test has no such loop. Sending it explicitly reproduces
        # what Houdini's own loop does when the tab closes.
        QtWidgets.QApplication.sendPostedEvents(
            None, QtCore.QEvent.Type.DeferredDelete)
        QtWidgets.QApplication.processEvents()

        self.assertTrue(
            notes.note_for(prefs, "material:asset-9").get("items", []),
            "the page is empty on disk - the edit died with the tab")


class _PanelStub:
    """Only what location_for reaches for: prefs, and the folder model
    under the name FileSection knows it by."""

    def __init__(self, prefs, folders):
        self.prefs = prefs
        self.file_folders_model = folders


if __name__ == "__main__":
    unittest.main()
