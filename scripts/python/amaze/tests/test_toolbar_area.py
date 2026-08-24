"""The Toolbar area: one table, and one fact per control.

BATCH 8 of the four-areas restructure. Five sync methods decided what
the toolbar showed, and they could disagree with each other because
each carried its own idea of which context it was in:

* `_sync_toolbar_for_mode` disabled three chips by asking
  `self._is_online()` - twice, in one method;
* the Capture button's rule lived somewhere else entirely, as
  `key == "file"` inside the activation path;
* and `takes_comments` was already a fact ON the context (batch 5),
  which is the shape the other three should have had.

A control's rule is now ONE entry in `MatLibPanel.TOOLBAR_CONTROLS` -
which control, which fact about the context, and whether the fact
governs enabled-ness or visibility - and one `_sync_toolbar(context)`
walks it. No toolbar path asks which WORLD it is in.

Written before the change, so the first version of these fails against
the shipped code.
"""

import ast
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.panel import sections  # noqa: E402
from amaze.tests import test_support  # noqa: E402

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TheToolbarIsATable(unittest.TestCase):

    def test_every_control_names_the_fact_it_follows(self):
        from amaze.panel.panel import MatLibPanel

        table = MatLibPanel.TOOLBAR_CONTROLS
        self.assertTrue(table, "the toolbar table is empty")
        for control, fact, verb in table:
            with self.subTest(control=control):
                self.assertTrue(control and fact)
                self.assertIn(
                    verb, ("enabled", "shown"),
                    "%s follows its fact by %r, which is neither "
                    "enabled-ness nor visibility" % (control, verb))
                self.assertTrue(
                    hasattr(sections.Section, fact),
                    "%s follows %r, which no context declares - so every "
                    "context answers the default and the control never "
                    "changes" % (control, fact))

    def test_the_four_known_controls_are_in_it(self):
        """Named, because a table that lost an entry is a control that
        silently stops following its context - which is how Capture came
        to be governed from the activation path instead."""
        from amaze.panel.panel import MatLibPanel

        listed = {control for control, _f, _v in MatLibPanel.TOOLBAR_CONTROLS}
        for control in ("cb_favsonly", "btn_notes", "btn_filter",
                        "btn_hip_capture"):
            self.assertIn(control, listed,
                          "%s no longer follows the context table" % control)

    def test_no_toolbar_sync_asks_which_WORLD_it_is_in(self):
        """`_is_online()` in a toolbar path is the thing this batch
        removes: the control's rule belongs to the CONTEXT, and the
        online world is a context like any other since batch 5."""
        source = open(os.path.join(PACKAGE, "panel", "panel.py"),
                      encoding="utf-8").read()
        tree = ast.parse(source)
        offenders = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.FunctionDef)
                    and node.name.startswith("_sync_toolbar")):
                continue
            for call in ast.walk(node):
                if (isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Attribute)
                        and call.func.attr == "_is_online"):
                    offenders.append("%s:%d" % (node.name, call.lineno))
        self.assertEqual(
            [], offenders,
            "a toolbar sync is testing which world it is in rather than "
            "asking the context: %s" % offenders)


class EveryContextDeclaresWhatItOffers(unittest.TestCase):

    #: context class -> what it must answer for each fact. The ONLINE
    #: row is the whole point: three of these are False there, and each
    #: used to be an `_is_online()` branch somewhere else.
    EXPECTED = {
        "MaterialSection": {"takes_comments": True, "takes_favourites": True,
                            "takes_filter_menu": True, "takes_capture": False},
        "FileSection": {"takes_comments": True, "takes_favourites": True,
                        "takes_filter_menu": True, "takes_capture": True},
        "GradientSection": {"takes_comments": True, "takes_favourites": True,
                            "takes_filter_menu": True, "takes_capture": False},
        "OnlineContext": {"takes_comments": False, "takes_favourites": False,
                          "takes_filter_menu": False, "takes_capture": False},
    }

    def test_each_context_answers_every_fact(self):
        for name, facts in self.EXPECTED.items():
            context = getattr(sections, name)
            for fact, expected in facts.items():
                with self.subTest(context=name, fact=fact):
                    self.assertEqual(
                        expected, getattr(context, fact),
                        "%s.%s is %r - the toolbar follows this, so the "
                        "control it governs is wrong in that context"
                        % (name, fact, getattr(context, fact)))

    def test_capture_is_offered_by_exactly_one_context(self):
        """It acts on the open SCENE, so it belongs where scene tiles
        live and nowhere else."""
        offering = [name for name in dir(sections)
                    if isinstance(getattr(sections, name), type)
                    and issubclass(getattr(sections, name), sections.Section)
                    and getattr(sections, name).takes_capture]
        self.assertEqual(["FileSection"], offering,
                         "Capture is offered by %s" % offering)


class TheToolbarFollowsTheContextLive(unittest.TestCase):
    """Driven through a real panel - the table is only worth having if
    walking it actually moves the widgets."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _state(self, control, verb):
        widget = getattr(self.panel, control, None)
        self.assertIsNotNone(widget, "%s is not on the panel" % control)
        return widget.isEnabled() if verb == "enabled" else not widget.isHidden()

    def test_each_control_matches_its_contexts_declaration(self):
        from amaze.panel.panel import MatLibPanel

        panel = self.panel
        self.addCleanup(self._restore)
        for key in ("material", "file"):
            panel.section_tabs.setChecked(key)
            QtWidgets.QApplication.processEvents()
            context = panel._section()
            for control, fact, verb in MatLibPanel.TOOLBAR_CONTROLS:
                with self.subTest(section=key, control=control):
                    self.assertEqual(
                        getattr(context, fact), self._state(control, verb),
                        "%s does not match %s.%s in the %s tab"
                        % (control, type(context).__name__, fact, key))

    def test_the_online_world_disables_the_local_controls_except_the_eye(self):
        from amaze.panel.panel import MatLibPanel

        panel = self.panel
        self.addCleanup(self._restore)
        panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        panel.enter_online_world()
        QtWidgets.QApplication.processEvents()

        context = panel._section()
        self.assertIsInstance(context, sections.OnlineContext,
                              "not in the online world, so this proves "
                              "nothing")
        for control, fact, verb in MatLibPanel.TOOLBAR_CONTROLS:
            with self.subTest(control=control):
                if control == "btn_filter":    # the one exception since 2026-08-24: online the eye carries the KIND filter, so the sync block re-enables it after its table row disables
                    self.assertTrue(
                        self._state(control, verb),
                        "the eye is dead in the online world - the "
                        "kind filter lives on it there")
                    continue
                self.assertEqual(
                    getattr(context, fact), self._state(control, verb),
                    "%s is live in the online world, where it has "
                    "nothing to act on" % control)

    def test_a_disabled_control_is_STILL_VISIBLE_in_the_online_world(self):
        """Disabled means greyed at half opacity - not GONE. The
        toolbar table answers these controls by ENABLED-ness, so the
        assertions above never look at visibility, and a second owner
        can hide one of them unseen: build_filter_menu hides
        btn_filter whenever the context offers no filter entries,
        which the online world always does. Reported live 2026-08-07 -
        the eye VANISHED online instead of greying out beside
        Favourites and Comments."""
        from amaze.panel.panel import MatLibPanel

        panel = self.panel
        self.addCleanup(self._restore)
        panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        panel.enter_online_world()
        QtWidgets.QApplication.processEvents()
        for control, _fact, verb in MatLibPanel.TOOLBAR_CONTROLS:
            if verb != "enabled":
                continue
            with self.subTest(control=control):
                widget = getattr(panel, control, None)
                self.assertIsNotNone(widget,
                                     "%s is not on the panel" % control)
                self.assertFalse(
                    widget.isHidden(),
                    "%s is HIDDEN in the online world - a control the "
                    "table answers by enabled-ness greys out there, it "
                    "does not vanish" % control)

    def _restore(self):
        panel = self.panel
        if panel._is_online():
            panel.leave_online_world()
        QtWidgets.QApplication.processEvents()


if __name__ == "__main__":
    unittest.main()
