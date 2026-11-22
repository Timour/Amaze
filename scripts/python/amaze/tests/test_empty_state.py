"""The empty state: the pane's rule for which page shows and its texts, and a button that clicks."""
import os
import shutil
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # the first QApplication picks the platform ▸p/first-app-picks-the-platform
from PySide6 import QtCore, QtGui, QtWidgets

from amaze import amazetheme
from amaze.pane import empty_state as rule
from amaze.panel import dragdrop_widgets, empty_state, grid
from amaze.tests import test_support

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])    # a subset run may have no earlier module that made one


def faces(panel) -> list:
    """Which of the grid pane's three widgets are shown: `table`, `list`, `blank`."""
    page = getattr(panel, "empty_page", None)
    return [name for name, widget in (
        ("table", getattr(panel, "thumbrows", None)),
        ("list", panel.thumblist),
        ("blank", page)) if widget is not None and not widget.isHidden()]


def pane_hit(panel):
    """The widget under a click in the middle of the grid pane."""
    host = grid.grid_pane_layout(panel).parentWidget()
    host.resize(600, 400)    # a never-shown pane is 100x30
    host.layout().activate()
    return host.childAt(host.rect().center())


def right_click_menu(testcase, panel, table) -> list:
    """(label, enabled) per entry of the menu a right-click in the grid pane opens."""
    grid.show_rows(panel, table)
    hit = pane_hit(panel)
    view = grid.visible_view(panel)
    testcase.assertTrue(hit is view or view.isAncestorOf(hit),
                        "a right-click on the empty grid reaches %s, not the grid"
                        % type(hit).__name__)
    hit = view.viewport()    # never shown, so its geometry is not laid out
    shown = []

    def _exec(menu, *_args, **_kwargs):
        shown.extend((action.text(), action.isEnabled())
                     for action in menu.actions() if not action.isSeparator())

    point = QtCore.QPoint(10, 10)
    with mock.patch.object(QtWidgets.QMenu, "exec_", _exec):
        QtWidgets.QApplication.sendEvent(hit, QtGui.QContextMenuEvent(
            QtGui.QContextMenuEvent.Reason.Mouse, point, hit.mapToGlobal(point)))
    return shown


class TheDeclarationsAreWellFormed(unittest.TestCase):
    """Read from the section classes: no panel needed."""

    def test_every_declared_handler_is_a_method_on_the_panel(self):
        """A handler that names no method from the panel hides its button without an error."""
        panel = test_support.fixture_panel(self)
        for table in (rule.SHARED,):
            for blank, words in table.items():
                self.assertLessEqual(words[0].count("%s"), 1, blank)
                self.assertLessEqual(words[1].count("%s"), 1, blank)
                self.assertEqual(
                    bool(words[2]), bool(words[3]),
                    "%s declares label %r against handler %r - a button that "
                    "does nothing, or a handler never offered"
                    % (blank, words[2], words[3]))
                handler = words[3]
                if not handler:
                    continue
                self.assertTrue(
                    callable(getattr(panel, handler, None)),
                    "%s names the handler %r, which no path from the panel reaches - "
                    "its button would be hidden with no error"
                    % (blank, handler))


class TheQuotedSearchIsElided(unittest.TestCase):

    def test_a_long_search_is_elided(self):
        out = rule._elide("x" * 200)
        self.assertLessEqual(len(out), rule.MAX_QUOTED)
        self.assertTrue(out.endswith("…"))
        self.assertEqual("metal", rule._elide("  metal  "))


class TheEngineChoosesWhichBlank(unittest.TestCase):

    def setUp(self):
        self.panel = test_support.fixture_panel(self)

    def test_a_search_that_matches_nothing_is_not_an_empty_library(self):
        """A search matching nothing has its own empty state; that the filter empties it is checked."""
        view = grid.visible_view(self.panel)
        if view.model() is None or not view.model().rowCount():
            self.skipTest("the fixture library has no rows to filter")
        self.assertEqual((None, ""), self.panel.pane.empty_state.verdict(),
                         "a library with rows in it returned an empty state")
        before = view.model().rowCount()
        self.panel.line_filter.setText("zzzz-no-such-asset")
        self.panel.pane.search(self.panel.line_filter.text())
        self.assertEqual(0, view.model().rowCount(),
                         "premise: the filter emptied the grid")

        blank, detail = self.panel.pane.empty_state.verdict()
        self.assertEqual(rule.NO_MATCH, blank,
                         "a filtered-to-nothing grid was taken for an empty "
                         "library, which tells the user their work is "
                         "gone")
        self.assertIn("zzzz", detail)

        self.panel.clear_filter_box()    # NOTHING ELSE: the real button makes no second filter call
        self.assertEqual("", self.panel.line_filter.text())
        self.assertEqual(before, view.model().rowCount(),
                         "the box is empty and the grid is still "
                         "filtered - the handler did not refilter")


class TheFavouritesBlankIsItsOwnBlank(unittest.TestCase):
    """The favourites filter with nothing starred has its own empty state, not the category one."""

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
            self.panel.pane.assets.toggle_favourite(starred)
        QtWidgets.QApplication.processEvents()

    def _favourites_only(self, on):
        self.panel.cb_favsonly.setChecked(on)
        QtWidgets.QApplication.processEvents()

    def test_no_favourites_at_all_is_its_own_blank(self):
        self._unstar_everything()
        before = self.proxy.rowCount()
        self._favourites_only(True)
        self.addCleanup(self._favourites_only, False)
        self.assertEqual(0, self.proxy.rowCount(),
                         "premise: the star emptied the grid")

        blank, _detail = self.panel.pane.empty_state.verdict()
        self.assertEqual(
            rule.NO_FAVOURITES, blank,
            "an unstarred library under the favourites filter was taken "
            "for an empty category, quoting an empty name")

        self.panel.clear_favourites_filter()    # NOTHING ELSE is called: the button's own handler
        QtWidgets.QApplication.processEvents()
        self.assertFalse(self.panel.cb_favsonly.isChecked())
        self.assertEqual(before, self.proxy.rowCount(),
                         "the star is off and the grid is still "
                         "filtered - the handler did not refilter")

    def test_a_search_still_outranks_the_favourites_blank(self):
        self._unstar_everything()
        self._favourites_only(True)
        self.addCleanup(self._favourites_only, False)
        self.panel.line_filter.setText("zzzz-no-such-asset")
        self.panel.pane.search(self.panel.line_filter.text())
        self.addCleanup(self.panel.clear_filter_box)

        blank, _detail = self.panel.pane.empty_state.verdict()
        self.assertEqual(
            rule.NO_MATCH, blank,
            "with a search active the search explains the empty grid, and "
            "clearing it must come first")

    def test_one_star_anywhere_makes_any_favourite_true(self):
        """A star just set must show in `_any_favourite` at once - no cache may be in between."""
        self._unstar_everything()
        self.assertFalse(rule._any_favourite(self.source))
        self.panel.pane.assets.toggle_favourite([self.proxy.index(0, 0)])
        QtWidgets.QApplication.processEvents()
        self.assertTrue(
            rule._any_favourite(self.source),
            "_any_favourite does not see the star just set, so the "
            "favourites empty state would say no favourites exist")

    def test_unstarring_a_multi_selection_unstars_the_selected_rows(self):
        """Under favourites-only a flip drops its proxy row, so map every row to source before any flip."""
        self._unstar_everything()
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


class TheButtonCanBeClicked(unittest.TestCase):
    """Attribute, hit test and real events each catch a different failure. ▸r/transparent-for-mouse"""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.page = empty_state.page(self.panel)
        if self.page is None:
            self.skipTest("no grid pane layout in this fixture")

    def test_the_page_is_not_transparent_for_mouse_events(self):
        attribute = QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents
        for widget in [self.page] + self.page.findChildren(QtWidgets.QWidget):
            self.assertFalse(
                widget.testAttribute(attribute),
                "%s ignores mouse events, so nothing inside it can be "
                "clicked" % (widget.objectName() or type(widget).__name__))

        self.page.say(self.panel, rule.NO_MATCH, "brick")
        self.page.resize(500, 400)
        self.page.layout().activate()
        button = self.page.button()
        self.assertTrue(button.isVisibleTo(self.page),
                        "premise: this empty state shows a button")
        centre = button.geometry().center()    # a HIT TEST, not a signal emission
        self.assertIs(button, self.page.childAt(centre),
                      "a click in the middle of the button reaches "
                      "another widget")

        fired = []    # real QMouseEvents, the overload that takes a device ▸r/transparent-for-mouse
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
    """The rendered label is measured, not assumed."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.page = empty_state.page(self.panel)
        if self.page is None:
            self.skipTest("no grid pane layout in this fixture")

    def test_the_sentence_fills_the_pane_and_is_centred(self):
        """Fills and centres, on a detached page: activate() undoes a resize. ▸r/label-centres-itself"""
        for width in (900, 500, 250):
            with self.subTest(width=width):
                page = empty_state.EmptyPage()
                self.addCleanup(page.deleteLater)
                page.say(self.panel, rule.NO_MATCH, "brick")
                page.resize(width, 400)
                page.layout().activate()
                label = page._text
                self.assertTrue(label.text(), "premise: it has a sentence")

                margins = self.page.layout().contentsMargins()
                room = width - margins.left() - margins.right()
                self.assertEqual(room, label.width(),
                                 "the sentence does not fill the pane, so "
                                 "its width depends on something else")
                self.assertLessEqual(
                    abs((label.x() + label.width() // 2) - width // 2), 1,
                    "the sentence is not centred in the pane")
                self.assertGreaterEqual(
                    label.height(), label.heightForWidth(label.width()),
                    "the sentence is shorter than its wrapped text needs")
        self.assertTrue(self.page._text.wordWrap())
        self.assertTrue(self.page._head.wordWrap())


class OnlyOneGridPaneWidgetIsShown(unittest.TestCase):

    def setUp(self):
        self.panel = test_support.fixture_panel(self)

    def _shown(self):
        return faces(self.panel)

    def test_the_blank_hides_both_views(self):
        empty_state.page(self.panel)
        self.panel._rows_mode = False
        grid.apply_grid_face(self.panel, True)
        self.assertEqual(["blank"], self._shown())
        grid.apply_grid_face(self.panel, False)
        self.assertEqual(["list"], self._shown(),
                         "clearing the empty state did not restore the view mode")
        grid.apply_grid_face(self.panel, True)
        grid.show_rows(self.panel, True)    # a view-mode switch: only the model clears an empty state
        self.assertEqual(["blank"], self._shown(),
                         "a view-mode change hid the empty state")


class AnEmptyCategoryIsThePlainGrid(unittest.TestCase):
    """A category with no rows shows its grid, empty: no text, its own right-click menu, its drops."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)

    def _select_a_new_category(self, key):
        """Add `Probe` with the sidebar's own menu action, select it, return the grid's proxy."""
        panel = self.panel
        panel.section_tabs.setChecked(key)
        QtWidgets.QApplication.processEvents()
        sidebar = panel.cat_list.model()
        sidebar.hide_empty = False    # on by default, which hides a row with no assets
        sidebar.invalidateFilter()
        with mock.patch.object(panel, "ask_name",
                               lambda _title, _default, then: then("Probe")):
            panel.pane.active_section().menu_add_category([], None)
        self.assertTrue(panel.pane.sidebar.select_key("Probe"),
                        "premise: Probe is a sidebar row")
        QtWidgets.QApplication.processEvents()
        proxy = grid.visible_view(panel).model()
        self.assertEqual(0, proxy.rowCount(), "premise: Probe is empty")
        return proxy

    def test_it_shows_the_grid_and_no_words(self):
        for key in ("material", "gradient", "code"):
            with self.subTest(section=key):
                proxy = self._select_a_new_category(key)
                self.assertTrue(proxy.sourceModel().rowCount(),
                                "premise: the section holds rows elsewhere")
                self.assertEqual((None, ""),
                                 self.panel.pane.empty_state.verdict(),
                                 "an empty category still returns an empty state")
                self.assertNotIn("blank", faces(self.panel),
                                 "a text covers the grid of an empty category")
                self.assertEqual(1, len(faces(self.panel)),
                                 "not exactly one grid view is up: %s"
                                 % faces(self.panel))

    def test_a_right_click_on_it_opens_the_grid_menu(self):
        """Code's menu offers New File over an empty selection, which is the point of the empty grid."""
        self._select_a_new_category("code")
        for table in (False, True):
            with self.subTest(list_mode=table):
                shown = right_click_menu(self, self.panel, table)
                self.assertTrue(shown, "the right-click opened no menu")
                self.assertEqual(("New File", True), shown[0],
                                 "the empty grid's menu does not start with "
                                 "an enabled New File: %s" % shown)

    def test_a_drop_on_it_reaches_the_widget_a_populated_grid_drops_on(self):
        """Qt delivers a drop to the first widget up from the cursor that accepts drops."""
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
                              "premise: a populated grid passes drops to the save widget")
        self._select_a_new_category("material")
        self.assertIs(populated, drop_target(),
                      "a node dropped on an empty category reaches another "
                      "widget than on a populated grid")

    def test_the_favourites_star_over_it_shows_the_grid(self):
        """The library has a star elsewhere, so the no-favourites empty state would be wrong."""
        panel = self.panel
        panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        proxy = grid.visible_view(panel).model()
        source = proxy.sourceModel()
        if not rule._any_favourite(source):
            panel.pane.assets.toggle_favourite([proxy.index(0, 0)])
            QtWidgets.QApplication.processEvents()
        self.assertTrue(rule._any_favourite(source), "premise: one star")
        self._select_a_new_category("material")
        panel.cb_favsonly.setChecked(True)
        self.addCleanup(panel.cb_favsonly.setChecked, False)
        QtWidgets.QApplication.processEvents()
        self.assertEqual((None, ""), panel.pane.empty_state.verdict())
        self.assertNotIn("blank", faces(panel))

    def test_a_search_in_it_still_shows_the_no_match_blank(self):
        self._select_a_new_category("code")
        self.panel.line_filter.setText("zzzz-no-such-asset")
        self.panel.pane.search(self.panel.line_filter.text())
        self.addCleanup(self.panel.clear_filter_box)
        QtWidgets.QApplication.processEvents()
        self.assertEqual(rule.NO_MATCH,
                         self.panel.pane.empty_state.verdict()[0])
        self.assertEqual(["blank"], faces(self.panel),
                         "a search with no hits left the grid up, unexplained")

    def test_an_unreadable_location_still_shows_the_unreachable_blank(self):
        panel = self.panel
        panel.section_tabs.setChecked("file")
        QtWidgets.QApplication.processEvents()
        gone = test_support.posix_path(
            test_support.scratch_dir("amaze_gone_")) + "/"
        self.addCleanup(shutil.rmtree, gone, True)
        self.assertTrue(panel.pane.file_folders_model.add_folder(gone),
                        "premise: the location registered")
        shutil.rmtree(gone)    # what an unmounted share looks like
        self.assertTrue(
            panel.pane.sidebar.select_key(gone),
            "premise: the location is a sidebar row")
        QtWidgets.QApplication.processEvents()
        self.assertEqual((rule.UNREACHABLE, gone),
                         panel.pane.empty_state.verdict())
        self.assertEqual(["blank"], faces(panel))


class AnEmptyLocationIsThePlainGrid(unittest.TestCase):
    """A readable File location with no files shows its grid, as an empty category does."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.panel.section_tabs.setChecked("file")
        QtWidgets.QApplication.processEvents()
        self.folders = self.panel.pane.file_folders_model
        self.files = self.panel.pane.file_files_model
        self.fixture = list(self.folders._folders())
        self.assertTrue(self.fixture, "premise: the fixture registers a location")

    def _register_empty(self):
        empty = test_support.posix_path(test_support.scratch_dir("amaze_empty_")) + "/"
        self.addCleanup(shutil.rmtree, empty, True)
        self.assertTrue(self.folders.add_folder(empty), "premise: the location registered")
        return empty

    def _drop_fixture(self):
        for path in self.fixture:
            self.assertTrue(self.folders.remove_folder(self.folders.row_of(path)),
                            "premise: the fixture location was not removed")

    def _click_row(self, row):
        """A left click on the sidebar row: select it, then call its clicked handler."""
        view = self.panel.cat_list
        view.selectionModel().setCurrentIndex(
            view.model().index(row, 0),
            QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.panel.pane.sidebar.show_row()
        QtWidgets.QApplication.processEvents()
        self.assertEqual(0, self.files.rowCount(), "premise: the grid lists no file")

    def _assert_plain_grid(self):
        self.assertEqual((None, ""), self.panel.pane.empty_state.verdict(),
                         "an empty location still returns an empty state")
        self.assertNotIn("blank", faces(self.panel),
                         "a text covers the grid of an empty location")
        self.assertEqual(1, len(faces(self.panel)),
                         "not exactly one grid view is up: %s" % faces(self.panel))

    def test_all_over_locations_that_hold_nothing_shows_the_grid(self):
        self._register_empty()
        self._drop_fixture()
        self._click_row(0)
        self._assert_plain_grid()

    def test_the_favourites_star_over_an_empty_location_shows_the_grid(self):
        """An empty location has nothing a star could hide, so its grid stays up."""
        self._click_row(self.folders.row_of(self._register_empty()))
        self._assert_plain_grid()
        self.panel.cb_favsonly.setChecked(True)
        self.addCleanup(self.panel.cb_favsonly.setChecked, False)
        QtWidgets.QApplication.processEvents()
        self._assert_plain_grid()

    def test_a_right_click_on_an_empty_location_opens_the_grid_menu(self):
        self._click_row(self.folders.row_of(self._register_empty()))
        section = self.panel.pane.active_section()
        menu, _handlers = grid.build_grid_menu(self.panel, section, [], None)
        self.addCleanup(menu.deleteLater)
        expected = [(action.text(), action.isEnabled()) for action in menu.actions()
                    if not action.isSeparator()]
        self.assertTrue(expected, "premise: File builds a grid menu over nothing selected")
        for table in (False, True):
            with self.subTest(list_mode=table):
                self.assertEqual(expected, right_click_menu(self, self.panel, table),
                                 "the right-click opened another menu")

class TheUnreachableBlankNamesARegisteredFolder(unittest.TestCase):
    """Only a scan clears the unreadable flag, so the empty state names only a registered folder."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.panel.pane.current_section = "file"
        self.model = self.panel.pane.file_files_model

    def test_a_folder_no_longer_registered_is_not_named(self):
        self.model._unreadable_folders.add("/no/such/folder/")
        self.addCleanup(self.model._unreadable_folders.discard,
                        "/no/such/folder/")
        self.assertEqual("", self.panel.pane.empty_state.unreadable_folder(),
                         "a folder that is not in the sidebar at all "
                         "was still named as the cause of the empty grid")
        folders = self.panel.pane.file_folders_model
        registered = folders._folders()
        if not registered:
            self.skipTest("the fixture registers no file folders")
        self.model._unreadable_folders.add(registered[0])
        self.addCleanup(self.model._unreadable_folders.discard,
                        registered[0])
        self.assertEqual(registered[0],
                         self.panel.pane.empty_state.unreadable_folder(),
                         "the empty state cannot name the folder it is about")

    def test_an_unreadable_folder_does_not_change_another_folders_blank(self):
        """The empty state describes the selected folder, never an unreadable folder elsewhere."""
        folders = self.panel.pane.file_folders_model
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
            "", self.panel.pane.empty_state.unreadable_folder(),
            "an empty result in a readable folder was blamed on an "
            "unreadable folder the user has not selected")

    def test_the_locate_button_moves_the_folder_the_message_names(self):
        """With the sidebar on All, the handler selects the named folder before the shared picker runs."""
        folders = self.panel.pane.file_folders_model
        target = test_support.fresh_files_folder(self)    # a second folder, so using the current one is caught
        folders.add_folder(target)
        self.addCleanup(folders.remove_folder, folders.row_of(target))
        self.assertIsNotNone(folders.row_of(target),
                             "premise: the second folder registered")
        self.panel.section_tabs.setChecked("file")    # the empty state shown is File's
        QtWidgets.QApplication.processEvents()
        self.panel.pane.sections["file"].select_sidebar_key("")    # the grid and the sidebar on All
        self.model._unreadable_folders.add(target)    # after the scans, which would clear it
        self.addCleanup(self.model._unreadable_folders.discard, target)
        self.panel.cat_list.setCurrentIndex(
            self.panel.cat_list.model().index(0, 0))    # the All row

        seen = {}

        def _picker(model, seen=seen, panel=self.panel):
            rows = panel.cat_list.selectedIndexes()
            seen["row"] = rows[0].row() if rows else -1

        original = self.panel.pane.files.locate_folder
        self.panel.pane.files.locate_folder = _picker
        self.addCleanup(setattr, self.panel, "locate_folder_user",
                        original)
        self.panel.locate_unreadable_folder()

        self.assertEqual(folders.row_of(target), seen.get("row"),
                         "the picker was handed a different folder "
                         "from the one the message names")


class EveryBoundProxyHasARefilteredSignal(unittest.TestCase):
    """`EmptyState.watch` follows `refiltered` on the grid's proxy; every bound proxy must have it."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def test_every_context_binds_a_proxy_with_refiltered(self):
        """Read off each context's own `activate()`, so a new section is covered too."""
        panel = self.panel
        self.addCleanup(lambda: panel.pane.active_section().activate())
        contexts = dict(panel.pane.sections, online=panel.pane.online_context)
        bound = {}
        for key, context in contexts.items():
            with mock.patch.object(panel, "bind_grid_views") as bind, \
                    mock.patch.object(panel.pane.matx_online_model, "reload"):
                context.activate()
            self.assertEqual(1, bind.call_count,
                             "%s bound the grid %d times" % (key, bind.call_count))
            bound[key] = bind.call_args[0][0]
        for key, proxy in bound.items():
            self.assertTrue(
                hasattr(proxy, "refiltered"),
                "%s binds a %s to the grid, which has no refiltered signal, so "
                "the empty state misses a search" % (key, type(proxy).__name__))
        self.assertEqual(len(bound), len({id(proxy) for proxy in bound.values()}),
                         "two contexts bind one proxy, so an activation never reached the grid")


if __name__ == "__main__":
    unittest.main()
