"""The empty grid: which blank, whose words, and a button that works - every test aimed at a defect that SHIPPED, the first build passing thirteen and reverting the same day (devlog 480)."""
import os
import shutil
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # BEFORE the app exists: the first module to build the QApplication picks the Qt platform for the whole hython, and on the native one the class font hash answers QListView 12pt against QTableView 13pt - which fails ANOTHER module's font assert ▸p/first-app-picks-the-platform
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

from amaze import amazetheme
from amaze.panel import dragdrop_widgets, empty_state, grid, sections
from amaze.panel import panel as panel_module
from amaze.tests import test_support

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])    # a widget cannot be built before this exists, and a SUBSET run has no earlier module to have made one


def faces(panel) -> list:
    """Which of the grid pane's three faces are up: `table`, `list`, `blank`."""
    page = getattr(panel, "empty_page", None)
    return [name for name, widget in (
        ("table", getattr(panel, "thumbtable", None)),
        ("list", panel.thumblist),
        ("blank", page)) if widget is not None and not widget.isHidden()]


def pane_hit(panel):
    """The widget a click in the middle of the grid pane lands on."""
    host = grid.grid_pane_layout(panel).parentWidget()
    host.resize(600, 400)    # a never-shown pane is 100x30
    host.layout().activate()
    return host.childAt(host.rect().center())


class TheDeclarationsAreWellFormed(unittest.TestCase):
    """Source-derived: no panel needed."""

    def test_every_section_declares_a_noun_and_a_first_run_blank(self):
        for key, cls in sections.SECTION_INDEX.items():
            if key == "online":
                continue                    # not a library section
            self.assertTrue(getattr(cls, "empty_noun", ""),
                            "%s declares no empty_noun, so the shared "
                            "sentences cannot name it" % key)
            self.assertIn(empty_state.NOTHING_YET, getattr(cls, "EMPTY", {}),
                          "%s declares no nothing-yet, and there is no "
                          "shared one to fall back to" % key)

    def test_every_declared_verb_is_a_method_on_the_panel(self):
        """A verb naming nothing hides its own button, silently."""
        tables = [empty_state.SHARED]
        tables += [getattr(c, "EMPTY", {})
                   for c in sections.SECTION_INDEX.values()]
        for table in tables:
            for blank, words in table.items():
                verb = words[3]
                if not verb:
                    continue
                self.assertTrue(
                    callable(getattr(panel_module.AmazePanel, verb, None)),
                    "%s names the verb %r, which is not a panel method - "
                    "its button would be hidden with no error"
                    % (blank, verb))

    def test_a_button_label_and_a_verb_arrive_together(self):
        """One without the other is a button that does nothing, or a working verb the user is never offered."""
        tables = [empty_state.SHARED]
        tables += [getattr(c, "EMPTY", {})
                   for c in sections.SECTION_INDEX.values()]
        for table in tables:
            for blank, words in table.items():
                self.assertEqual(
                    bool(words[2]), bool(words[3]),
                    "%s declares label %r against verb %r"
                    % (blank, words[2], words[3]))

    def test_no_headline_carries_more_than_one_placeholder(self):
        for table in [empty_state.SHARED] + [
                getattr(c, "EMPTY", {})
                for c in sections.SECTION_INDEX.values()]:
            for blank, words in table.items():
                self.assertLessEqual(words[0].count("%s"), 1, blank)
                self.assertLessEqual(words[1].count("%s"), 1, blank)


class TheQuotedStringCannotRunAway(unittest.TestCase):

    def test_a_long_search_is_elided(self):
        out = empty_state._elide("x" * 200)
        self.assertLessEqual(len(out), empty_state.MAX_QUOTED)
        self.assertTrue(out.endswith("…"))

    def test_a_short_search_is_left_alone(self):
        self.assertEqual("metal", empty_state._elide("  metal  "))


class TheEngineSaysWhichBlank(unittest.TestCase):

    def setUp(self):
        self.panel = test_support.fixture_panel(self)

    def test_a_library_with_rows_in_it_says_nothing(self):
        view = grid.visible_view(self.panel)
        if view.model() is None or not view.model().rowCount():
            self.skipTest("the fixture library has no rows to show")
        self.assertEqual((None, ""), empty_state.verdict(self.panel))

    def test_a_search_that_matches_nothing_is_not_an_empty_library(self):
        """THE ONE THE ORIGINAL SKIPPED ITSELF ON - its premise was a `skipTest`, so a filter that failed to bite reported success, and it is an ASSERT here."""
        view = grid.visible_view(self.panel)
        if view.model() is None or not view.model().rowCount():
            self.skipTest("the fixture library has no rows to filter")
        self.panel.line_filter.setText("zzzz-no-such-asset")
        self.panel.filter_thumb_view()
        self.assertEqual(0, view.model().rowCount(),
                         "premise: the filter emptied the grid")

        blank, detail = empty_state.verdict(self.panel)
        self.assertEqual(empty_state.NO_MATCH, blank,
                         "a filtered-to-nothing grid read as an empty "
                         "library, which tells the user their work is "
                         "gone")
        self.assertIn("zzzz", detail)


class TheClearButtonActuallyRefilters(unittest.TestCase):
    """DEFECT 3 - every reverted test hand-called `filter_thumb_view()` after clearing, the second push the real button never made, so all passed against a broken verb (devlog 480)."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)

    def test_clearing_through_the_verb_alone_restores_the_rows(self):
        view = grid.visible_view(self.panel)
        if view.model() is None or not view.model().rowCount():
            self.skipTest("the fixture library has no rows to filter")
        before = view.model().rowCount()

        self.panel.line_filter.setText("zzzz-no-such-asset")
        self.panel.filter_thumb_view()
        self.assertEqual(0, view.model().rowCount(), "premise: filtered")

        # NOTHING ELSE IS CALLED. That is the whole test.
        self.panel.clear_filter_box()

        self.assertEqual("", self.panel.line_filter.text())
        self.assertEqual(before, view.model().rowCount(),
                         "the box is empty and the grid is still "
                         "filtered - the verb did not refilter")


class TheFavouritesBlankIsItsOwnBlank(unittest.TestCase):
    """The favourites star over nothing starred used to fall through to the category blank, which quoted an empty category name."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        view = grid.visible_view(self.panel)
        proxy = view.model() if view is not None else None
        if proxy is None or not proxy.rowCount():
            self.skipTest("the fixture library has no rows")
        self.view, self.proxy = view, proxy
        self.source = proxy.sourceModel()
        self.role = self.source.FavoriteRole

    def _unstar_everything(self):
        starred = [self.proxy.index(r, 0)
                   for r in range(self.proxy.rowCount())
                   if self.proxy.index(r, 0).data(self.role)]
        if starred:
            self.panel.grid_toggle_favourite(starred)
        QtWidgets.QApplication.processEvents()

    def _favourites_only(self, on):
        self.panel.cb_favsonly.setChecked(on)
        QtWidgets.QApplication.processEvents()

    def test_no_favourites_at_all_is_its_own_blank(self):
        self._unstar_everything()
        self._favourites_only(True)
        self.addCleanup(self._favourites_only, False)
        self.assertEqual(0, self.proxy.rowCount(),
                         "premise: the star emptied the grid")

        blank, _detail = empty_state.verdict(self.panel)
        self.assertEqual(
            empty_state.NO_FAVOURITES, blank,
            "an unstarred library behind the favourites star read as "
            "an empty category, quoting an empty name")

    def test_a_search_still_outranks_the_favourites_blank(self):
        self._unstar_everything()
        self._favourites_only(True)
        self.addCleanup(self._favourites_only, False)
        self.panel.line_filter.setText("zzzz-no-such-asset")
        self.panel.filter_thumb_view()
        self.addCleanup(self.panel.clear_filter_box)

        blank, _detail = empty_state.verdict(self.panel)
        self.assertEqual(
            empty_state.NO_MATCH, blank,
            "with a search active the search explains the blank, and "
            "clearing it must come first")

    def test_one_star_anywhere_flips_the_discriminator(self):
        """A star set THIS instant must reach `_any_favourite` - no cache may sit under it."""
        self._unstar_everything()
        self.assertFalse(empty_state._any_favourite(self.source))
        self.panel.grid_toggle_favourite([self.proxy.index(0, 0)])
        QtWidgets.QApplication.processEvents()
        self.assertTrue(
            empty_state._any_favourite(self.source),
            "the star just set is invisible to the discriminator, so "
            "the favourites blank would claim no favourites exist")

    def test_unstarring_a_multi_selection_lands_on_the_selected_rows(self):
        """Under favourites-only, the first flip REMOVES its row from the proxy, so proxy indexes mapped inside the loop land on the wrong rows - every selected row must be mapped to source BEFORE any flip."""
        self._unstar_everything()
        self.panel.grid_toggle_favourite([self.proxy.index(0, 0),
                                          self.proxy.index(1, 0)])
        QtWidgets.QApplication.processEvents()
        self._favourites_only(True)
        self.addCleanup(self._favourites_only, False)
        self.assertEqual(2, self.proxy.rowCount(),
                         "premise: two favourites showing")
        self.panel.grid_toggle_favourite([self.proxy.index(0, 0),
                                          self.proxy.index(1, 0)])
        QtWidgets.QApplication.processEvents()
        left = sum(1 for r in range(self.source.rowCount())
                   if self.source.index(r, 0).data(self.role))
        self.assertEqual(0, left,
                         "unstarring both favourites left %d starred - "
                         "the loop flipped through stale proxy rows"
                         % left)

    def test_the_show_all_verb_alone_restores_the_rows(self):
        self._unstar_everything()
        before = self.proxy.rowCount()
        self._favourites_only(True)
        self.assertEqual(0, self.proxy.rowCount(), "premise: emptied")

        # NOTHING ELSE IS CALLED. That is the whole test.
        self.panel.clear_favourites_filter()
        QtWidgets.QApplication.processEvents()

        self.assertFalse(self.panel.cb_favsonly.isChecked())
        self.assertEqual(before, self.proxy.rowCount(),
                         "the star is off and the grid is still "
                         "filtered - the verb did not refilter")


class TheButtonCanBeClicked(unittest.TestCase):
    """DEFECT 2 - a re-set `WA_TransparentForMouseEvents` is caught only by the FIRST of these three, `childAt` and a directly-sent event both bypassing the parent's transparency, so each guards a different failure. ▸r/transparent-for-mouse (devlog 480)"""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.page = empty_state.page(self.panel)
        if self.page is None:
            self.skipTest("no grid pane layout in this fixture")

    def test_the_page_does_not_refuse_mouse_events(self):
        attribute = QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents
        for widget in [self.page] + self.page.findChildren(QtWidgets.QWidget):
            self.assertFalse(
                widget.testAttribute(attribute),
                "%s refuses mouse events, so nothing inside it can be "
                "clicked" % (widget.objectName() or type(widget).__name__))

    def test_the_button_is_what_a_click_at_its_centre_finds(self):
        """A HIT TEST, not a signal emission."""
        self.page.say(self.panel, empty_state.NO_MATCH, "brick")
        self.page.resize(500, 400)
        self.page.layout().activate()
        button = self.page.button()
        self.assertTrue(button.isVisibleTo(self.page),
                        "premise: this blank offers a button")

        centre = button.geometry().center()
        self.assertIs(button, self.page.childAt(centre),
                      "a click in the middle of the button lands on "
                      "something else")

    def test_pressing_and_releasing_it_runs_the_verb(self):
        """Real QMouseEvents through the device-carrying overload (the short one is deprecated in Qt 6 and prints per run), so nothing about delivery is assumed. ▸r/transparent-for-mouse"""
        self.page.say(self.panel, empty_state.NO_MATCH, "brick")
        self.page.resize(500, 400)
        self.page.layout().activate()
        button = self.page.button()

        fired = []
        button.clicked.connect(lambda *_: fired.append(True))
        middle = QtCore.QPointF(button.rect().center())
        pointer = QtGui.QPointingDevice.primaryPointingDevice()
        for kind in (QtCore.QEvent.Type.MouseButtonPress,
                     QtCore.QEvent.Type.MouseButtonRelease):
            QtWidgets.QApplication.sendEvent(button, QtGui.QMouseEvent(
                kind, middle, middle, QtCore.Qt.MouseButton.LeftButton,
                QtCore.Qt.MouseButton.LeftButton,
                QtCore.Qt.KeyboardModifier.NoModifier, pointer))
        self.assertTrue(fired, "a press and release on the button did "
                               "not produce a click")


class TheTextWraps(unittest.TestCase):
    """DEFECT 1 - no reverted test measured a rendered label at all."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.page = empty_state.page(self.panel)
        if self.page is None:
            self.skipTest("no grid pane layout in this fixture")

    def test_the_sentence_fills_the_pane_and_is_centred(self):
        """Both halves, each with its own way of going wrong - at its sizeHint the text clips, capped by a maximum it sits left - measured on a DETACHED page, since `resize` on a managed layout child is undone by the next `activate()`. ▸r/label-centres-itself"""
        for width in (900, 500, 250):
            with self.subTest(width=width):
                page = empty_state.EmptyPage()
                self.addCleanup(page.deleteLater)
                page.say(self.panel, empty_state.NO_MATCH, "brick")
                page.resize(width, 400)
                page.layout().activate()
                label = page._text
                self.assertTrue(label.text(), "premise: it has a sentence")

                margins = self.page.layout().contentsMargins()
                room = width - margins.left() - margins.right()
                self.assertEqual(room, label.width(),
                                 "the sentence does not fill the pane, so "
                                 "it is at some other width's mercy")
                self.assertLessEqual(
                    abs((label.x() + label.width() // 2) - width // 2), 1,
                    "the sentence is not centred in the pane")
                self.assertGreaterEqual(
                    label.height(), label.heightForWidth(label.width()),
                    "the sentence is shorter than its wrapped text needs")

    def test_the_label_is_told_to_wrap(self):
        self.assertTrue(self.page._text.wordWrap())
        self.assertTrue(self.page._head.wordWrap())


class OnlyOneFaceIsUp(unittest.TestCase):

    def setUp(self):
        self.panel = test_support.fixture_panel(self)

    def _shown(self):
        return faces(self.panel)

    def test_the_blank_hides_both_views(self):
        empty_state.page(self.panel)
        grid.apply_grid_face(self.panel, True)
        self.assertEqual(["blank"], self._shown())

    def test_clearing_the_blank_restores_the_view_mode(self):
        empty_state.page(self.panel)
        self.panel._table_mode = False
        grid.apply_grid_face(self.panel, True)
        grid.apply_grid_face(self.panel, False)
        self.assertEqual(["list"], self._shown())

    def test_a_view_mode_change_does_not_dismiss_a_blank(self):
        """`show_table` runs on a view-mode switch and must not be the thing that decides a blank is over - only the model is."""
        empty_state.page(self.panel)
        grid.apply_grid_face(self.panel, True)
        grid.show_table(self.panel, True)
        self.assertEqual(["blank"], self._shown())


class TheQuoteRidesTheFirstRunBlankOnly(unittest.TestCase):
    """A section may hang a quotation under its first-run sentence; nothing else carries one, and the page must clear it when moving to a blank that has none."""

    def test_a_declared_quote_is_a_line_and_an_attribution(self):
        for key, cls in sections.SECTION_INDEX.items():
            quote = getattr(cls, "QUOTE", None)
            if not quote:
                continue
            self.assertEqual(
                2, len(quote),
                "%s declares a QUOTE that is not (line, attribution)"
                % key)
            self.assertTrue(all(str(part).strip() for part in quote),
                            "%s declares a QUOTE with a blank half"
                            % key)

    def test_only_the_first_run_blank_carries_it(self):
        panel = test_support.fixture_panel(self)
        for blank in (empty_state.NO_MATCH, empty_state.NO_FAVOURITES,
                      empty_state.UNREACHABLE):
            self.assertEqual(("", ""),
                             empty_state.quote_for(panel, blank),
                             "%s drew a quotation" % blank)

    def test_the_page_clears_it_between_blanks(self):
        panel = test_support.fixture_panel(self)
        page = empty_state.page(panel)
        page.say(panel, empty_state.NOTHING_YET, "")
        page.say(panel, empty_state.NO_MATCH, "brick")
        self.assertTrue(page._quote.isHidden(),    # isHidden, never isVisible: a child of a never-shown parent answers False either way ▸r/qt-text-checklists
                        "the quotation stayed up over a blank that "
                        "declares none")
        self.assertEqual("", page._quote.text())


class AnEmptyCategoryIsThePlainGrid(unittest.TestCase):
    """A category with no rows shows its grid, empty: no words, its own right-click menu, its drops."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)

    def _stand_on_a_new_category(self, key):
        """Add `Probe` through the sidebar's own verb, stand on it, answer the grid's proxy."""
        panel = self.panel
        panel.section_tabs.setChecked(key)
        QtWidgets.QApplication.processEvents()
        sidebar = panel.cat_list.model()
        sidebar.hide_empty = False    # on by default, which hides a row with no assets
        sidebar.invalidateFilter()
        with mock.patch.object(panel, "ask_category_name",
                               lambda _title, _default="": "Probe"):
            panel._section().menu_add_category([], None)
        self.assertTrue(panel._stand_on_category("Probe"),
                        "premise: Probe is a sidebar row")
        QtWidgets.QApplication.processEvents()
        proxy = grid.visible_view(panel).model()
        self.assertEqual(0, proxy.rowCount(), "premise: Probe is empty")
        return proxy

    def test_it_shows_the_grid_and_no_words(self):
        for key in ("material", "gradient", "code"):
            with self.subTest(section=key):
                proxy = self._stand_on_a_new_category(key)
                self.assertTrue(proxy.sourceModel().rowCount(),
                                "premise: the section holds rows elsewhere")
                self.assertEqual((None, ""),
                                 empty_state.verdict(self.panel),
                                 "an empty category still asks for a blank")
                self.assertNotIn("blank", faces(self.panel),
                                 "words cover the grid of an empty category")
                self.assertEqual(1, len(faces(self.panel)),
                                 "not exactly one grid view is up: %s"
                                 % faces(self.panel))

    def test_a_right_click_on_it_opens_the_grid_menu(self):
        """Code's menu offers New File over an empty selection, which is the point of the empty grid."""
        self._stand_on_a_new_category("code")
        for table in (False, True):
            with self.subTest(list_mode=table):
                grid.show_table(self.panel, table)
                hit = pane_hit(self.panel)
                view = grid.visible_view(self.panel)
                self.assertTrue(hit is view or view.isAncestorOf(hit),
                                "a right-click on the empty category lands "
                                "on %s, not the grid" % type(hit).__name__)
                hit = view.viewport()    # never shown, so its geometry is not laid out
                shown = []

                def _exec(menu, *_args, **_kwargs):
                    shown.extend((action.text(), action.isEnabled())
                                 for action in menu.actions()
                                 if not action.isSeparator())

                point = QtCore.QPoint(10, 10)
                with mock.patch.object(QtWidgets.QMenu, "exec_", _exec):
                    QtWidgets.QApplication.sendEvent(
                        hit, QtGui.QContextMenuEvent(
                            QtGui.QContextMenuEvent.Reason.Mouse, point,
                            hit.mapToGlobal(point)))
                self.assertTrue(shown, "the right-click opened no menu")
                self.assertEqual(("New File", True), shown[0],
                                 "the empty grid's menu does not lead with "
                                 "a live New File: %s" % shown)

    def test_a_drop_on_it_lands_where_a_populated_grid_sends_it(self):
        """Qt hands a drop to the first widget up from the cursor that accepts drops."""
        def drop_target():
            widget = pane_hit(self.panel)
            while widget is not None and not widget.acceptDrops():
                widget = widget.parentWidget()
            return widget

        self.panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        self.assertTrue(grid.visible_view(self.panel).model().rowCount(),
                        "premise: All shows rows")
        populated = drop_target()
        self.assertIsInstance(populated,
                              dragdrop_widgets.DragDropCentralWidget,
                              "premise: a populated grid drops on the save door")
        self._stand_on_a_new_category("material")
        self.assertIs(populated, drop_target(),
                      "a node dropped on an empty category goes somewhere "
                      "a populated grid does not send it")

    def test_the_favourites_star_over_it_shows_the_grid(self):
        """The library has a star elsewhere, so the no-favourites blank would be false here."""
        panel = self.panel
        panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        proxy = grid.visible_view(panel).model()
        source = proxy.sourceModel()
        if not empty_state._any_favourite(source):
            panel.grid_toggle_favourite([proxy.index(0, 0)])
            QtWidgets.QApplication.processEvents()
        self.assertTrue(empty_state._any_favourite(source), "premise: one star")
        self._stand_on_a_new_category("material")
        panel.cb_favsonly.setChecked(True)
        self.addCleanup(panel.cb_favsonly.setChecked, False)
        QtWidgets.QApplication.processEvents()
        self.assertEqual((None, ""), empty_state.verdict(panel))
        self.assertNotIn("blank", faces(panel))

    def test_a_search_in_it_still_says_nothing_matches(self):
        self._stand_on_a_new_category("code")
        self.panel.line_filter.setText("zzzz-no-such-asset")
        self.panel.filter_thumb_view()
        self.addCleanup(self.panel.clear_filter_box)
        QtWidgets.QApplication.processEvents()
        self.assertEqual(empty_state.NO_MATCH,
                         empty_state.verdict(self.panel)[0])
        self.assertEqual(["blank"], faces(self.panel),
                         "a search with no hits left the grid up, unexplained")

    def test_a_section_with_nothing_saved_keeps_its_first_run_blank(self):
        """The fixture saves no Node asset; a new category there is still a section with nothing."""
        proxy = self._stand_on_a_new_category("cop")
        self.assertEqual(0, proxy.sourceModel().rowCount(),
                         "premise: the fixture saves no Node asset")
        self.assertEqual((empty_state.NOTHING_YET, ""),
                         empty_state.verdict(self.panel))
        self.assertEqual(["blank"], faces(self.panel))
        self.assertEqual(amazetheme.EMPTY_NODE[empty_state.NOTHING_YET][0],
                         self.panel.empty_page._head.text())

    def test_an_unreadable_location_still_says_so(self):
        panel = self.panel
        panel.section_tabs.setChecked("file")
        QtWidgets.QApplication.processEvents()
        gone = test_support.posix_path(
            test_support.scratch_dir("amaze_gone_")) + "/"
        self.addCleanup(shutil.rmtree, gone, True)
        self.assertTrue(panel.file_folders_model.add_folder(gone),
                        "premise: the location registered")
        shutil.rmtree(gone)    # what an unmounted share looks like
        self.assertTrue(
            panel._stand_on_category(os.path.basename(gone.rstrip("/"))),
            "premise: the location is a sidebar row")
        QtWidgets.QApplication.processEvents()
        self.assertEqual((empty_state.UNREACHABLE, gone),
                         empty_state.verdict(panel))
        self.assertEqual(["blank"], faces(panel))


class TheUnreachableBlankPointsAtSomethingReal(unittest.TestCase):
    """Only a SCAN of a folder clears its unreadable flag, so a folder that was located or removed would go on being named forever."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.panel.current_section = "file"
        self.model = self.panel.file_files_model

    def test_a_folder_no_longer_registered_is_not_named(self):
        self.model._unreadable_folders.add("/no/such/folder/")
        self.addCleanup(self.model._unreadable_folders.discard,
                        "/no/such/folder/")
        self.assertEqual("", empty_state.unreadable_folder(self.panel),
                         "a folder that is not in the sidebar at all "
                         "was still blamed for the empty grid")

    def test_a_registered_one_is(self):
        folders = self.panel.file_folders_model
        registered = folders._folders()
        if not registered:
            self.skipTest("the fixture registers no file folders")
        self.model._unreadable_folders.add(registered[0])
        self.addCleanup(self.model._unreadable_folders.discard,
                        registered[0])
        self.assertEqual(registered[0],
                         empty_state.unreadable_folder(self.panel),
                         "the blank cannot name the folder it is about")

    def test_a_dead_folder_does_not_hijack_another_folders_blank(self):
        """The blank describes the folder being LOOKED AT - standing in a healthy folder, an empty result must not be blamed on a dead folder elsewhere."""
        folders = self.panel.file_folders_model
        registered = folders._folders()
        if not registered:
            self.skipTest("the fixture registers no file folders")
        healthy = test_support.fresh_files_folder(self)
        folders.add_folder(healthy)
        self.addCleanup(folders.remove_folder, folders.row_of(healthy))
        self.model._unreadable_folders.add(registered[0])
        self.addCleanup(self.model._unreadable_folders.discard,
                        registered[0])
        self.model.set_folder(healthy)
        self.assertEqual(
            "", empty_state.unreadable_folder(self.panel),
            "an empty result in a healthy folder was blamed on a dead "
            "folder the user is not even looking at")

    def test_the_locate_button_moves_the_folder_the_message_names(self):
        """The blank can be up while the sidebar sits on All, so the verb must SELECT the named folder before handing over to the shared picker."""
        folders = self.panel.file_folders_model
        target = test_support.fresh_files_folder(self)    # a SECOND registered folder, so a verb that simply used whatever was current would still be caught
        folders.add_folder(target)
        self.addCleanup(folders.remove_folder, folders.row_of(target))
        self.assertIsNotNone(folders.row_of(target),
                             "premise: the second folder registered")
        self.model._unreadable_folders.add(target)
        self.addCleanup(self.model._unreadable_folders.discard, target)
        self.panel.cat_list.setCurrentIndex(
            self.panel.cat_list.model().index(0, 0))    # the All row

        seen = {}

        def _picker(model, seen=seen, panel=self.panel):
            rows = panel.cat_list.selectedIndexes()
            seen["row"] = rows[0].row() if rows else -1

        original = self.panel._locate_folder_user
        self.panel._locate_folder_user = _picker
        self.addCleanup(setattr, self.panel, "_locate_folder_user",
                        original)
        self.panel.locate_unreadable_folder()

        self.assertEqual(folders.row_of(target), seen.get("row"),
                         "the picker was handed a different folder "
                         "from the one the message names")


if __name__ == "__main__":
    unittest.main()
