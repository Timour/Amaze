"""The Empty State Engine: which blank, and when nothing is drawn.

A first-run panel is the only screen with nothing else to look at, and
Amaze had no empty-state text at all. Twenty states (five sections,
four blanks) is exactly the shape that becomes five disagreeing copies
unless the arithmetic of "is this empty, and why" lives once.

WHAT THESE PIN, and why each is here rather than left to the eye:

* the VERDICT, which is the engine's whole job - a section's own words
  are a declaration and cannot be wrong, but picking `nothing-yet` when
  the truth is `nothing-matches` tells the user their library is empty
  when it is their typo;
* the DECLARATIONS' shape, because a verb naming a method that does not
  exist gives a button that silently does nothing - the same defect the
  GRID_MENU tables have a test for;
* the WIDTH BANDS, measured rather than chosen (research.md ▸ WHAT A
  SQUEEZED PANEL ACTUALLY LEAVES THE GRID).
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.helpers import theme                          # noqa: E402
from amaze.panel import empty_state, sections            # noqa: E402
from amaze.tests import test_support                     # noqa: E402,F401


class TheDeclarationsAreWellFormed(unittest.TestCase):
    """Read from the registry, so a sixth section joins these by
    existing rather than by someone remembering to add it."""

    def test_every_section_declares_a_noun_and_a_first_run_blank(self):
        missing = []
        for key, cls in sections.SECTION_INDEX.items():
            if not getattr(cls, "empty_noun", ""):
                missing.append("%s: no empty_noun" % key)
            if empty_state.NOTHING_YET not in (getattr(cls, "EMPTY", None)
                                               or {}):
                missing.append("%s: no nothing-yet" % key)
        self.assertEqual(
            [], sorted(missing),
            "a section has no first-run empty state, so its blank grid "
            "teaches nothing on the one screen with nothing else to "
            "look at: %s" % ", ".join(sorted(missing)))

    def test_every_declared_verb_is_a_method_on_the_panel(self):
        """A verb naming nothing is a button that does nothing. The
        engine hides such a button rather than showing a dead one, so
        this would never raise - it would just quietly stop teaching."""
        from amaze.panel import panel as panel_module

        dead = []
        tables = [("SHARED", empty_state.SHARED)]
        for key, cls in sections.SECTION_INDEX.items():
            tables.append((key, getattr(cls, "EMPTY", None) or {}))
        for where, table in tables:
            for blank, words in table.items():
                verb = words[3]
                if verb and not hasattr(panel_module.MatLibPanel, verb):
                    dead.append("%s/%s -> %s" % (where, blank, verb))
        self.assertEqual(
            [], sorted(dead),
            "an empty state names a panel method that does not exist, "
            "so its button is hidden and the state teaches without "
            "offering the action: %s" % ", ".join(sorted(dead)))

    def test_a_headline_survives_with_no_sentence_and_no_button(self):
        """The narrow band shows the headline alone, so a headline that
        only makes sense above its body is a headline that says nothing
        at 250px."""
        for key, cls in sections.SECTION_INDEX.items():
            words = (getattr(cls, "EMPTY", None) or {}).get(
                empty_state.NOTHING_YET)
            headline = words[0]
            self.assertTrue(headline.strip(), "%s has an empty headline"
                            % key)
            self.assertNotIn("%s", headline,
                             "%s's first-run headline interpolates - "
                             "there is nothing to quote back before "
                             "anything has been saved" % key)
            self.assertLess(len(headline), 40,
                            "%s's headline is long enough to wrap at "
                            "the narrow band, where it is the only "
                            "thing shown" % key)


class TheEngineSaysWhichBlank(unittest.TestCase):
    """The verdict, driven through a real panel."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _verdict(self):
        return empty_state.verdict(self.panel)[0]

    def test_a_library_with_materials_in_it_says_nothing(self):
        """The case that must stay silent - and the reason `refresh`
        returns before touching a widget when the grid has rows."""
        self.panel.current_section = "material"
        self.panel.apply_view_mode()
        from amaze.panel import grid

        view = grid.visible_view(self.panel)
        if view.model() is None or view.model().rowCount() == 0:
            self.skipTest("the fixture library has no materials to show")
        self.assertIsNone(self._verdict(),
                          "a grid with rows in it drew an empty state")

    def test_a_search_that_matches_nothing_is_not_an_empty_library(self):
        """The distinction that matters most: telling a user their
        library is empty when what is empty is their search."""
        from amaze.panel import grid

        self.panel.current_section = "material"
        self.panel.apply_view_mode()
        view = grid.visible_view(self.panel)
        if view.model() is None or view.model().rowCount() == 0:
            self.skipTest("the fixture library has no materials to show")

        # BOTH HALVES OF A KEYSTROKE. The box is wired on `textEdited`,
        # which is USER edits only - `setText` does not emit it, so an
        # earlier version of this test set the text, filtered nothing,
        # and skipped itself. A skipped test is dead cover, and this is
        # the one case in the file that matters most.
        typed = "zzzz-no-such-material-zzzz"
        box = self.panel.line_filter
        box.setText(typed)
        self.panel.filter_thumb_view()
        self.addCleanup(self.panel.filter_thumb_view)
        self.addCleanup(box.clear)
        QtWidgets.QApplication.processEvents()
        self.assertEqual(0, view.model().rowCount(),
                         "premise: the filter emptied the grid")

        blank, detail = empty_state.verdict(self.panel)
        self.assertEqual(empty_state.NO_MATCH, blank,
                         "an unmatched search reported the library "
                         "empty, which is a different and much worse "
                         "sentence")
        self.assertIn("zzzz", detail,
                      "the search string is not quoted back, so the "
                      "user cannot see their own typo")


class TheQuotedStringCannotRunAway(unittest.TestCase):
    """A search string is the user's own text and has no length limit.

    One pasted path makes the headline wider than any panel; the widest
    headline measured was already the one carrying it (207px).
    """

    def test_a_long_search_is_elided(self):
        long = "/Volumes/studio/textures/wood/oak/varnished/closeup"
        short = empty_state._elide(long)
        self.assertLessEqual(len(short), empty_state.MAX_QUOTED)
        self.assertTrue(short.endswith("…"))

    def test_a_short_search_is_left_alone(self):
        self.assertEqual("metal", empty_state._elide("  metal  "))


class TheBandsAreMeasuredNotChosen(unittest.TestCase):
    """Width decides how much is shown, and the numbers come from the
    panel's own type (research.md). Asserted as an ORDER rather than as
    three literals, so re-measuring moves them together."""

    def test_the_bands_are_ordered_and_leave_room_for_the_headline(self):
        self.assertLess(empty_state.MIN_WIDTH, empty_state.FULL_WIDTH,
                        "the button band starts below the hide band")
        self.assertGreaterEqual(
            empty_state.MIN_WIDTH, 239,
            "the narrow band is below the measured width of the widest "
            "headline plus its inset, so the one thing still shown "
            "there wraps")

    def test_nothing_is_drawn_when_there_is_no_room(self):
        surface = empty_state.EmptyState()
        self.addCleanup(surface.deleteLater)
        surface.set_state("No materials saved yet", "body", "Button")
        surface.set_verb(lambda: None)

        surface.resize(theme.ui_px(empty_state.MIN_WIDTH) - 1, 400)
        surface._apply_band()
        self.assertTrue(surface.isHidden(),
                        "a grid too narrow to read drew a clipped "
                        "sentence instead of nothing")

        surface.resize(600, theme.ui_px(empty_state.MIN_HEIGHT) - 1)
        surface._apply_band()
        self.assertTrue(surface.isHidden(),
                        "a grid too short to read drew into it anyway")

    def test_the_button_goes_before_the_sentence_does(self):
        """The sentence teaches the gesture and the button only
        shortcuts what it explains, so the button is what goes."""
        surface = empty_state.EmptyState()
        self.addCleanup(surface.deleteLater)
        surface.set_state("No materials saved yet", "body", "Button")
        surface.set_verb(lambda: None)

        surface.resize(theme.ui_px(empty_state.FULL_WIDTH), 400)
        surface._apply_band()
        self.assertTrue(surface.button().isVisibleTo(surface),
                        "the button is missing at full width")
        self.assertTrue(surface._can_show_body())

        surface.resize(theme.ui_px(empty_state.FULL_WIDTH) - 1, 400)
        surface._apply_band()
        self.assertFalse(surface.button().isVisibleTo(surface),
                         "the button survived below the full band, "
                         "where there is not room for it and the words")
        self.assertFalse(surface._can_show_body(),
                         "the sentence is still drawn where it cannot "
                         "fit beside the headline")


if __name__ == "__main__":
    unittest.main()
