"""The empty grid: which blank, whose words, and a button that works - every test aimed at a defect that SHIPPED, the first build passing thirteen and reverting the same day (devlog 480)."""
import unittest

from PySide6 import QtCore, QtGui, QtWidgets

from amaze.panel import empty_state, grid, sections
from amaze.panel import panel as panel_module
from amaze.tests import test_support

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])    # a widget cannot be built before this exists, and a SUBSET run has no earlier module to have made one


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
                    callable(getattr(panel_module.MatLibPanel, verb, None)),
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
        """`_any_favourite` separates the favourites blank from the category blank - a star set THIS instant must be seen, so no cache may sit under it."""
        self._unstar_everything()
        self.assertFalse(empty_state._any_favourite(self.source))
        self.panel.grid_toggle_favourite([self.proxy.index(0, 0)])
        QtWidgets.QApplication.processEvents()
        self.assertTrue(
            empty_state._any_favourite(self.source),
            "the star just set is invisible to the discriminator, so "
            "the favourites blank would claim no favourites exist")

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
                page.say(self.panel, empty_state.NOTHING_HERE, "Metal")
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
        page = getattr(self.panel, "empty_page", None)
        return [name for name, widget in (
            ("table", getattr(self.panel, "thumbtable", None)),
            ("list", self.panel.thumblist),
            ("blank", page)) if widget is not None and not widget.isHidden()]

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


if __name__ == "__main__":
    unittest.main()
