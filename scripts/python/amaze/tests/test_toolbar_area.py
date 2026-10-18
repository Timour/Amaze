"""The Toolbar area: one table, one fact per control. A control's rule is ONE entry naming the control, the fact about the context, and whether that fact governs enabled-ness or visibility. NO toolbar path asks which WORLD it is in. ▸archive/test_toolbar_area.py
"""

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


class TheToolbarIsATable(unittest.TestCase):

    def test_every_control_names_the_fact_it_follows(self):
        from amaze.panel.panel import AmazePanel

        table = AmazePanel.TOOLBAR_CONTROLS
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
        listed = {control for control, _f, _v in table}
        for control in ("cb_favsonly", "btn_notes", "btn_filter",
                        "btn_hip_capture"):
            self.assertIn(control, listed,
                          "%s no longer follows the context table, so it "
                          "silently stops following its context" % control)


class EveryContextDeclaresWhatItOffers(unittest.TestCase):

    #: Context class -> what it must answer for each fact.
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
        offering = [name for name in dir(sections)    # capture acts on the open SCENE: File only
                    if isinstance(getattr(sections, name), type)
                    and issubclass(getattr(sections, name), sections.Section)
                    and getattr(sections, name).takes_capture]
        self.assertEqual(["FileSection"], offering,
                         "Capture is offered by %s" % offering)


class TheToolbarFollowsTheContextLive(unittest.TestCase):
    """Driven through a real panel - the table is only worth having if walking it moves the widgets."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _state(self, control, verb):
        widget = getattr(self.panel, control, None)
        self.assertIsNotNone(widget, "%s is not on the panel" % control)
        return widget.isEnabled() if verb == "enabled" else not widget.isHidden()

    def test_each_control_matches_its_contexts_declaration(self):
        from amaze.panel.panel import AmazePanel

        panel = self.panel
        self.addCleanup(self._restore)
        for key in ("material", "file"):
            panel.section_tabs.setChecked(key)
            QtWidgets.QApplication.processEvents()
            context = panel._section()
            for control, fact, verb in AmazePanel.TOOLBAR_CONTROLS:
                with self.subTest(section=key, control=control):
                    self.assertEqual(
                        getattr(context, fact), self._state(control, verb),
                        "%s does not match %s.%s in the %s tab"
                        % (control, type(context).__name__, fact, key))

    def test_the_online_world_disables_the_local_controls_except_the_eye(self):
        from amaze.panel.panel import AmazePanel

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
        for control, fact, verb in AmazePanel.TOOLBAR_CONTROLS:
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
        for control, _fact, verb in AmazePanel.TOOLBAR_CONTROLS:
            if verb != "enabled":
                continue
            with self.subTest(control=control, asked="visible"):
                self.assertFalse(
                    getattr(panel, control).isHidden(),
                    "%s is HIDDEN in the online world - a control the "
                    "table answers by enabled-ness greys out there, it "
                    "does not vanish" % control)

    def _restore(self):
        panel = self.panel
        if panel._is_online():
            panel.leave_online_world()
        QtWidgets.QApplication.processEvents()


class TheToolbarStandsOnItsFrame(unittest.TestCase):
    """The toolbar's height, edges, gaps and controls land where B01 draws them. ▸r/toolbar-from-frame"""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def setUp(self):
        from PySide6 import QtCore
        from amaze import amazetheme
        from amaze.helpers import theme
        panel = self.panel
        panel.section_tabs.setChecked("material")
        panel.prefs.view_mode = "list"
        panel.apply_view_mode()
        self.addCleanup(panel.apply_view_mode)
        self.addCleanup(setattr, panel.prefs, "view_mode", "grid")
        self.px = theme.ui_px
        self.frame = amazetheme.DIALOG_LAYOUT["B01"]
        self.node = {tuple(amazetheme.drawn_name(n)[:2]): n for n in self.frame["nodes"]
                     if len(amazetheme.drawn_name(n)) > 1}
        width, height = self.frame["frame"]
        panel.toolbar_layout.setGeometry(QtCore.QRect(0, 0, self.px(width), self.px(height)))
        QtWidgets.QApplication.processEvents()

    def _widget(self, name):
        layout = self.panel.toolbar_layout
        for i in range(layout.count()):
            widget = layout.itemAt(i).widget()
            if widget is not None and widget.objectName() == name:
                return widget
        self.fail("the toolbar has no %s" % name)

    def _drawn(self, kind):
        from amaze import amazetheme
        return amazetheme.drawn_by_owner("B01", kind)

    def test_the_row_is_its_drawn_height(self):
        height = self.px(self.frame["frame"][1])
        row = self.panel.toolbar_row
        self.assertEqual((height, height), (row.minimumHeight(), row.maximumHeight()))

    def test_every_control_left_of_the_label_is_where_it_is_drawn(self):
        """Left of the label nothing depends on the font, so every box is exact."""
        drawn = dict(self._drawn("button"), click_slider=self.node[("slider", "click_slider")])
        label_x = self.node[("label", "filter_label")][1]
        checked = 0
        for name, n in drawn.items():
            if n[1] >= label_x:
                continue
            geometry = self._widget(name).geometry()
            with self.subTest(control=name):
                self.assertEqual(tuple(self.px(v) for v in n[1:5]),
                                 (geometry.x(), geometry.y(), geometry.width(), geometry.height()))
            checked += 1
        self.assertGreater(checked, 5, "too few controls checked to be a test")
        self.assertEqual(self.px(label_x), self._widget("filter_label").x(),
                         "the label does not start where it is drawn")

    def test_the_box_and_the_gear_are_where_they_are_drawn(self):
        """Right of the label positions move with the font, so the box is held by its gap."""
        label = self._widget("filter_label").geometry()
        field, box = self.node[("field", "line_filter")], self._widget("line_filter").geometry()
        drawn_label = self.node[("label", "filter_label")]
        self.assertEqual(self.px(field[1] - (drawn_label[1] + drawn_label[3])),
                         box.x() - (label.x() + label.width()))
        self.assertEqual((self.px(field[3]), self.px(field[4])), (box.width(), box.height()))
        gear, drawn_gear = self._widget("btn_prefs").geometry(), self.node[("button", "btn_prefs")]
        self.assertEqual(tuple(self.px(v) for v in drawn_gear[1:5]),
                         (gear.x(), gear.y(), gear.width(), gear.height()))

    def test_every_icon_is_its_drawn_size_and_place(self):
        for owner, icon in self._drawn("icon").items():
            if owner == "line_filter":
                continue
            button, widget = self.node[("button", owner)], self._widget(owner)
            with self.subTest(control=owner):
                self.assertEqual(self.px(icon[3]), widget._icon_size)
                self.assertEqual(icon[1] - button[1], (button[3] - icon[3]) // 2,
                                 "the drawn icon is not where the button paints it")

    def test_the_magnifier_is_where_it_is_drawn(self):
        icon, field = self.node[("icon", "line_filter")], self.node[("field", "line_filter")]
        magnifier = self.panel.filter_icon_label.geometry()
        self.assertEqual(tuple(self.px(v) for v in (icon[1] - field[1], icon[2] - field[2],
                                                    icon[3], icon[4])),
                         (magnifier.x(), magnifier.y(), magnifier.width(), magnifier.height()))


if __name__ == "__main__":
    unittest.main()
