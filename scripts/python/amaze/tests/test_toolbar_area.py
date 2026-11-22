"""The toolbar is one table: each control names one context fact and whether it enables or shows."""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.sections import online as online_section, base as section_base  # noqa: E402
from amaze.tests import test_support  # noqa: E402


class TheToolbarIsATable(unittest.TestCase):

    def test_every_control_names_the_fact_it_follows(self):
        from amaze.panel.panel import AmazePanel

        table = AmazePanel.TOOLBAR_CONTROLS
        self.assertTrue(table, "the toolbar table is empty")
        for control, fact, effect in table:
            with self.subTest(control=control):
                self.assertTrue(control and fact)
                self.assertIn(
                    effect, ("enabled", "shown"),
                    "%s follows its fact by %r, which is neither "
                    "enabled-ness nor visibility" % (control, effect))
                self.assertTrue(
                    hasattr(section_base.Section, fact),
                    "%s follows %r, which no context declares - so every "
                    "context returns the default and the control never "
                    "changes" % (control, fact))
        listed = {control for control, _f, _v in table}
        for control in ("cb_favsonly", "btn_notes", "btn_info", "btn_filter",
                        "btn_hip_capture"):
            self.assertIn(control, listed,
                          "%s is missing from `TOOLBAR_CONTROLS`, so it "
                          "no longer changes with the active section" % control)


class EveryContextDeclaresWhatItOffers(unittest.TestCase):

    #: Context class -> what it must answer for each fact.
    EXPECTED = {
        "MaterialSection": {"takes_comments": True, "takes_favourites": True,
                            "takes_filter_menu": True, "takes_capture": True},
        "FileSection": {"takes_comments": True, "takes_favourites": True,
                        "takes_filter_menu": True, "takes_capture": True},
        "GradientSection": {"takes_comments": True, "takes_favourites": True,
                            "takes_filter_menu": True, "takes_capture": True},
        "OnlineContext": {"takes_comments": False, "takes_favourites": False,
                          "takes_filter_menu": False, "takes_capture": False},
    }

    def test_each_context_declares_every_fact(self):
        for name, facts in self.EXPECTED.items():
            context = test_support.section_class(name)
            for fact, expected in facts.items():
                with self.subTest(context=name, fact=fact):
                    self.assertEqual(
                        expected, getattr(context, fact),
                        "%s.%s is %r - the toolbar follows this, so the "
                        "control it governs is wrong in that context"
                        % (name, fact, getattr(context, fact)))
        declining = [name for name, cls in test_support.section_classes().items()    # any library tile takes a capture
                     if not cls.takes_capture]
        self.assertEqual(["OnlineContext"], declining,
                         "Capture is disabled in %s" % declining)


class TheToolbarFollowsTheContextLive(unittest.TestCase):
    """Run on a real panel - the table is only useful if applying it changes the widgets."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _state(self, control, effect):
        widget = getattr(self.panel, control, None)
        self.assertIsNotNone(widget, "%s is not on the panel" % control)
        return widget.isEnabled() if effect == "enabled" else not widget.isHidden()

    def test_each_control_matches_its_contexts_declaration(self):
        from amaze.panel.panel import AmazePanel

        panel = self.panel
        self.addCleanup(self._restore)
        for key in ("material", "file"):
            panel.section_tabs.setChecked(key)
            QtWidgets.QApplication.processEvents()
            context = panel.pane.active_section()
            for control, fact, effect in AmazePanel.TOOLBAR_CONTROLS:
                with self.subTest(section=key, control=control):
                    self.assertEqual(
                        getattr(context, fact), self._state(control, effect),
                        "%s does not match %s.%s in the %s tab"
                        % (control, type(context).__name__, fact, key))

    def test_the_online_world_disables_the_local_controls_except_the_eye(self):
        from amaze.panel.panel import AmazePanel

        panel = self.panel
        self.addCleanup(self._restore)
        panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        panel.pane.enter_online()
        QtWidgets.QApplication.processEvents()

        context = panel.pane.active_section()
        self.assertIsInstance(context, online_section.OnlineContext,
                              "not in the online world, so this proves "
                              "nothing")
        for control, fact, effect in AmazePanel.TOOLBAR_CONTROLS:
            with self.subTest(control=control):
                if control == "btn_filter":    # the one exception: online the eye button holds the kind filter, re-enabled by the sync block
                    self.assertTrue(
                        self._state(control, effect),
                        "the eye is disabled in the online world - the "
                        "kind filter is on that button there")
                    continue
                self.assertEqual(
                    getattr(context, fact), self._state(control, effect),
                    "%s is enabled in the online world, where it has "
                    "nothing to act on" % control)
        for control, _fact, effect in AmazePanel.TOOLBAR_CONTROLS:
            if effect != "enabled":
                continue
            with self.subTest(control=control, asked="visible"):
                self.assertFalse(
                    getattr(panel, control).isHidden(),
                    "%s is HIDDEN in the online world - a control the "
                    "table sets by enabled-ness is greyed out there, "
                    "not hidden" % control)

    def _restore(self):
        panel = self.panel
        if panel.pane.is_online():
            panel.pane.leave_online()
        QtWidgets.QApplication.processEvents()


class TheColoursFollowAHoudiniThemeSwitch(unittest.TestCase):
    """A theme switch sets new `pluto_` colours and a new app palette; what Amaze colours follows it."""

    def test_a_theme_switch_recolours_the_search_field_slider_and_tiles(self):
        from PySide6 import QtCore, QtGui
        from amaze.panel import delegates
        panel = test_support.fixture_panel(self)
        app = QtWidgets.QApplication.instance()
        switched = QtGui.QColor("#123456")
        for role in ("pluto_field", "pluto_surfaceLow"):
            self.addCleanup(app.setProperty, role, app.property(role))
            app.setProperty(role, switched)
        QtWidgets.QApplication.sendEvent(panel, QtCore.QEvent(QtCore.QEvent.Type.ApplicationPaletteChange))
        self.assertIn("#123456", panel.line_filter.styleSheet(), "the search field kept the old theme")
        self.assertEqual(switched, panel.click_slider.RIGHT_COLOR, "the slider kept the old theme")
        self.assertEqual(switched, delegates.AssetItemDelegate.THUMB_BG_COLOR.fget(None), "the tiles kept the old theme")


class TheToolbarMatchesFrameB01(unittest.TestCase):
    """The toolbar's height, edges, gaps and controls match frame B01. ▸r/toolbar-from-frame"""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def setUp(self):
        from PySide6 import QtCore
        from amaze import amazetheme
        from amaze.helpers import theme
        panel = self.panel
        panel.section_tabs.setChecked("material")
        panel.pane.prefs.view_mode = "list"
        panel.apply_view_mode()
        self.addCleanup(panel.apply_view_mode)
        self.addCleanup(setattr, panel.pane.prefs, "view_mode", "grid")
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

    def test_info_takes_the_generate_buttons_place(self):
        self.assertEqual("btn_info", self._widget("btn_info").objectName())
        names = [self.panel.toolbar_layout.itemAt(i).widget().objectName()
                 for i in range(self.panel.toolbar_layout.count())
                 if self.panel.toolbar_layout.itemAt(i).widget() is not None]
        self.assertNotIn("btn_generate", names, "Generate is still a toolbar button")
        self.assertFalse(hasattr(self.panel, "btn_generate"))

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

    def test_the_box_and_the_right_end_buttons_are_where_they_are_drawn(self):
        """Right of the label positions move with the font, so the box is checked by its gap."""
        label = self._widget("filter_label").geometry()
        field, box = self.node[("field", "line_filter")], self._widget("line_filter").geometry()
        drawn_label = self.node[("label", "filter_label")]
        self.assertEqual(self.px(field[1] - (drawn_label[1] + drawn_label[3])),
                         box.x() - (label.x() + label.width()))
        self.assertEqual((self.px(field[3]), self.px(field[4])), (box.width(), box.height()))
        for name in ("btn_notes", "btn_info"):
            widget, drawn = self._widget(name).geometry(), self.node[("button", name)]
            with self.subTest(control=name):
                self.assertEqual(tuple(self.px(v) for v in drawn[1:5]),
                                 (widget.x(), widget.y(), widget.width(), widget.height()))

    def test_a_narrow_panel_keeps_six_pixels_between_the_box_and_comments(self):
        from PySide6 import QtCore
        from amaze import amazetheme
        self.assertEqual(6, amazetheme.TOOLBAR_SEARCH_END_GAP)
        box, comments = self._widget("line_filter"), self._widget("btn_notes")
        least = self.panel.toolbar_layout.minimumSize().width()    # narrower than this nothing fits
        for width in (least, least + 40, least + 120):
            self.panel.toolbar_layout.setGeometry(QtCore.QRect(0, 0, width, self.px(self.frame["frame"][1])))
            QtWidgets.QApplication.processEvents()
            with self.subTest(width=width):
                self.assertLess(box.width(), self.px(self.node[("field", "line_filter")][3]),
                                "premise: the box is squeezed at this width")
                self.assertEqual(self.px(6), comments.geometry().left() - (box.geometry().right() + 1))

    def test_the_row_is_in_the_frames_order_with_the_stretch_after_the_box(self):
        from amaze.tests import test_support
        field_x = self.node[("field", "line_filter")][1]
        drawn = sorted((n[1], name) for (kind, name), n in self.node.items()
                       if kind in ("button", "slider", "label", "field"))
        expected = [name for x, name in drawn if x <= field_x] + ["stretch"] \
            + [name for x, name in drawn if x > field_x]
        self.assertEqual(expected, [entry for entry in test_support.toolbar_row(self.panel)
                                    if entry != "gap"])

    def test_three_buttons_show_their_own_colour_while_on_and_the_toolbar_blue_at_rest(self):
        from PySide6 import QtGui
        from amaze import amazetheme
        lit = {"btn_online": amazetheme.ONLINE_ICON_COLOR, "btn_notes": amazetheme.COMMENT_ICON_COLOR,
               "btn_info": amazetheme.INFO_ICON_COLOR}
        rest = QtGui.QColor(amazetheme.MENU_IDLE_BODY).name()
        for name, colour in lit.items():
            button = self._widget(name)
            with self.subTest(control=name):
                self.assertEqual({rest}, self._solid_colours(button._pms[(False, False)]))
                self.assertEqual({QtGui.QColor(colour).name()},
                                 self._solid_colours(button._pms[(True, False)]))

    @staticmethod
    def _solid_colours(pixmap):
        """The colours of a pixmap's fully opaque pixels."""
        image = pixmap.toImage()
        return {image.pixelColor(x, y).name() for x in range(image.width())
                for y in range(image.height()) if image.pixelColor(x, y).alpha() == 255}

    def test_every_icon_is_its_drawn_size_and_place(self):
        for owner, icon in self._drawn("icon").items():
            if owner == "line_filter":
                continue
            button, widget = self.node[("button", owner)], self._widget(owner)
            with self.subTest(control=owner):
                self.assertEqual(self.px(icon[3]), widget._icon_size)
                from amaze.helpers import ui_helpers
                painted = ui_helpers.icon_rect(widget, widget._icon_size)
                self.assertEqual((self.px(float(icon[1] - button[1])), self.px(float(icon[2] - button[2]))),
                                 (painted.x(), painted.y()), "the drawn icon is not where the button paints it")

    def test_the_magnifier_is_where_it_is_drawn(self):
        icon, field = self.node[("icon", "line_filter")], self.node[("field", "line_filter")]
        magnifier = self.panel.filter_icon_label.geometry()
        self.assertEqual(tuple(self.px(v) for v in (icon[1] - field[1], icon[2] - field[2],
                                                    icon[3], icon[4])),
                         (magnifier.x(), magnifier.y(), magnifier.width(), magnifier.height()))


if __name__ == "__main__":
    unittest.main()
