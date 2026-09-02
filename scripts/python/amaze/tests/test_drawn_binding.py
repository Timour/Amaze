"""The dialogs READ the drawn document: a node moved or resized in Figma moves the real widget, and a drawn label that gets renamed costs one pin rather than the dialog. ▸p/one-design-document"""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # BEFORE the app exists: the first module to build the QApplication picks the platform for the whole hython ▸p/first-app-picks-the-platform
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

from amaze import amazetheme  # noqa: E402
from amaze.core import debug  # noqa: E402
from amaze.helpers import theme, ui_helpers  # noqa: E402
from amaze.tests import test_support  # noqa: E402

TEXT_SUFFIX = " ▸ text"

PREFS_FRAMES = ("D04", "D05", "D06", "D07", "D08")

PINNED_BUTTONS = {    # every text button Preferences takes from the document, written out here so a lost pin fails rather than quietly widening to the host font
    "D04": ("Clean Up Library", "Reload Library", "Open Library Folder",
            "Rename", "Delete", "Default", "Delete Local Cache"),
    "D08": ("Check for Updates", "Report a Bug...", "Open Log",
            "Save Log...", "Clear Log"),
}

PREFS_COMBOS = {    # (frame, attribute, drawn width) - the combos each tab builds, in creation order
    "D04": (("cbb_library_user", 196),),
    "D05": (("_combo_geo_shading", 165), ("_combo_geo_bg", 165),
            ("cbb_matx_res", 72)),
    "D07": (("_combo_path_style", 105), ("_combo_icon_weight", 145)),
}

UNPAIRED = {}    # a drawn `▸ text` node with no rect of its own kind around it; every one must be named, because the ordinary reading of a missing pair is a document edit that lost the rect

LABEL_RIGHT = {    # where a form label's drawn box ENDS - the label column's right edge, per frame. A QLabel ending anywhere else is a FIELD-side label and has to be pinned, which is what the D08 version line was not
    "D02": (63,),               # the drawn field column less `D02_LABEL_GAP`
    "D11": (63, 378),           # two halves, each less `D11_LABEL_GAP`
    "D04": (amazetheme.PREFS_LABEL_RIGHT,),
    "D05": (amazetheme.PREFS_LABEL_RIGHT,),
    "D06": (amazetheme.PREFS_LABEL_RIGHT,),
    "D07": (amazetheme.PREFS_LABEL_RIGHT,),
    "D08": (amazetheme.PREFS_LABEL_RIGHT,),
    "D09": (amazetheme.SAVE_LABEL_RIGHT,),
    "D13": (amazetheme.SAVE_LABEL_RIGHT,),
    "D14": (amazetheme.D14_LABEL_RIGHT,),
}

STRETCHED_FIELDS = {    # frame and kind whose fields fill the column instead of wearing a width
    ("D02", "QLineEdit"), ("D02", "QComboBox"),
    ("D11", "QLineEdit"), ("D11", "QComboBox"),
}

LOOSE_LABELS = {    # (frame, kind, x, y) of a label drawn BESIDE or ABOVE its control rather than in a column
    ("D01", "QLabel", 18, 81),
    ("D02", "QLabel", 202, 160),
    ("D02", "QLabel", 212, 220),
}


def plain_rects(frame_key, kind):
    return amazetheme.drawn_boxes(frame_key).get((kind, None), ())


def inside(node, box):
    """The node's drawn rect sits inside `box`."""
    return bool(box) and (box[0] <= node[1] and box[1] <= node[2]
                          and box[0] + box[2] >= node[1] + node[3]
                          and box[1] + box[3] >= node[2] + node[4])


def band_box(frame_key):
    found = plain_rects(frame_key, "header band")
    return found[0] if found else ()


DRAWN_EXEMPT = (    # (does this node need no pin, why) - EVERY drawn node off this table must pin a live widget through the binding
    (lambda f, n: n[0].endswith(TEXT_SUFFIX),
     "sample text drawn INSIDE a rect; the rect is what the widget wears"),
    (lambda f, n: n[0].startswith("QTabBar"),
     "the tab strip and its chips: Qt lays the bar out from the tab "
     "labels, and nothing in the app places a tab"),
    (lambda f, n: n[0] == "QScrollBar",
     "Qt's own, shown and hidden by the view it belongs to"),
    (lambda f, n: n[0] == "header band",
     "a painted strip the frame's full width, `HEADER_BAND_H` tall"),
    (lambda f, n: n[0] == "QLabel" and inside(n, band_box(f)),
     "the band's own text, placed and sized by `ui_helpers.header_band`"),
    (lambda f, n: n[0].startswith("icon grid"),
     "a drawing device standing in for the `D02_CELL` cells the chooser "
     "builds itself, and the note that says so"),
    (lambda f, n: n[0] == "QWidget ▸ group divider",
     "a painted rule spanning the content column, `PREFS_DIVIDER_H` tall"),
    (lambda f, n: n[0] == "ToggleSwitch",
     "the drawn pill is the TRACK the widget paints inside a wider box - "
     "`TheToggleIsTheDrawnPill` holds the two together"),
    (lambda f, n: n[0] == "QLabel" and n[1] + n[3] in LABEL_RIGHT.get(f, ()),
     "a form label: the drawn box is its TEXT, right-aligned inside the "
     "label column the row pins"),
    (lambda f, n: n[0] == "QLineEdit"
     and any(inside(n, box) for box in plain_rects(f, "QSpinBox")),
     "the editor INSIDE a spin box, which Qt insets by 1 - pinning it "
     "takes back the 2 the document gives the box around it"),
    (lambda f, n: (f, n[0]) in STRETCHED_FIELDS,
     "D02 and D11 are the frames that RESIZE: their fields fill the "
     "column, and the drawn width is the width at the drawn size"),
    (lambda f, n: n[0] == "CodeEditor",
     "the editor is what D11's resize grows; `D11_EDITOR_H` is its floor"),
    (lambda f, n: n[0] == "_LineNumberArea",
     "the gutter is as wide as the digits the host font draws in it"),
    (lambda f, n: (f,) + n[:3] in LOOSE_LABELS,
     "drawn at its own text width beside its control; the widget takes "
     "the host font's and yields before the row overflows"),
)


def build_every_frame(case):
    """One live dialog per drawn frame, so the binding's pins are the real ones - a frame nothing builds cannot be proven bound."""
    from amaze.dialogs import (base_dialog, code_dialog, icon_dialog,
                               prefs_dialog, save_dialog, user_dialog)
    versions = ui_helpers.DesignedDialog(None, title="brushed_steel")   # D01, built the way the panel builds it
    versions.add_field(QtWidgets.QComboBox(versions))
    versions.add_field(QtWidgets.QLineEdit(versions),
                       label=amazetheme.LABEL_CHANGE_NAME)
    versions.add_buttons(amazetheme.BTN_CANCEL, amazetheme.BTN_APPLY)
    built = (
        versions,
        icon_dialog.IconDialog(None, 0.0, None, tile_name="rocks1",
                               tile_tags="", categories=["Metal"],
                               tile_category="Metal"),
        prefs_dialog.PrefsDialog(test_support.fixture_prefs(case),
                                 panel=None),
        save_dialog.SaveDialog(["Metal"], "Metal", name="rocks1"),
        code_dialog.CodeDialog(["Metal"]),
        base_dialog.NameDialog(),
        user_dialog.UserPickerDialog({"u1": "Plum"}),
    )
    for dialog in built:
        case.addCleanup(dialog.deleteLater)
    return built


def text_nodes(kind_wanted):
    """(frame, kind, text, box) for every drawn `<Kind> ▸ text` node of one kind, over the whole document - so a frame added later is covered without touching this file."""
    found = []
    for frame_key, frame in amazetheme.DIALOG_LAYOUT.items():
        for kind, x, y, w, h, text in frame["nodes"]:
            if kind.endswith(TEXT_SUFFIX) and \
                    kind[:-len(TEXT_SUFFIX)] == kind_wanted:
                found.append((frame_key, kind_wanted, text, (x, y, w, h)))
    return found


def pinned(case, widget):
    """The widget's pinned (w, h) - asserting it IS pinned, since reading `width()` would answer whatever the last layout pass happened to give it."""
    case.assertEqual(
        (widget.minimumWidth(), widget.minimumHeight()),
        (widget.maximumWidth(), widget.maximumHeight()),
        "%s is not pinned at all" % widget)
    return widget.minimumWidth(), widget.minimumHeight()


class TheDocumentPairsEveryDrawnButton(unittest.TestCase):
    """`drawn_boxes` is a pure derivation over `DIALOG_LAYOUT`: it pairs a drawn label with the rect around it, so nothing new has to be maintained beside the table."""

    def setUp(self):
        amazetheme.forget_drawn_boxes()
        self.addCleanup(amazetheme.forget_drawn_boxes)

    def test_every_drawn_button_label_finds_its_rect(self):
        missing = []
        for frame_key, kind, text, box in text_nodes("QPushButton"):
            if (frame_key, kind, text) in UNPAIRED:
                continue
            if amazetheme.drawn_boxes(frame_key).get((kind, text)) is None:
                missing.append("%s %s %r at %s" % (frame_key, kind, text, box))
        self.assertEqual(
            [], missing,
            "these drawn button labels sit inside no rect of their own "
            "kind, so nothing can be pinned from them:\n  "
            + "\n  ".join(missing))

    def test_the_walk_really_sees_the_document(self):
        """A walk that matched nothing would pass the test above forever. ▸p/vacuous-register"""
        self.assertGreaterEqual(
            len(text_nodes("QPushButton")), 20,
            "the document walk found almost no drawn button labels, so "
            "its silence means nothing")

    def test_a_named_exception_is_still_really_unpaired(self):
        """An exemption kept after the document grew the rect would hide the pin that should have been made."""
        for (frame_key, kind, text), why in UNPAIRED.items():
            with self.subTest(node="%s %s" % (frame_key, text)):
                self.assertIsNone(
                    amazetheme.drawn_boxes(frame_key).get((kind, text)),
                    "%s %r now HAS a drawn rect - drop the exemption "
                    "(%s)" % (frame_key, text, why))

    def test_a_drawn_box_is_the_rect_and_not_the_label(self):
        """The pair's value is the enclosing RECT: D09 draws `OK` 15 wide inside a 31-wide button, and pinning the label's own box would draw half a button."""
        self.assertEqual((254, 94, 31, 22),
                         amazetheme.drawn_boxes("D09")[("QPushButton", "OK")])
        self.assertEqual(
            (293, 94, 50, 22),
            amazetheme.drawn_boxes("D09")[("QPushButton", "Cancel")])

    def test_the_textless_rects_come_back_in_document_order(self):
        """A combo carries no label of its own to pin by, so the frame's `QComboBox` rects in drawn order are what answers the tab's combos."""
        self.assertEqual(
            ((148, 162, 165, 22), (148, 190, 165, 22), (148, 315, 72, 22)),
            amazetheme.drawn_boxes("D05")[("QComboBox", None)])

    def test_an_unknown_frame_answers_empty(self):
        self.assertEqual({}, amazetheme.drawn_boxes("D99"))


class TheToggleIsTheDrawnPill(unittest.TestCase):
    """`ToggleSwitch`'s own numbers against the pills the document draws - the constants and the drawing agree, or the switch is a shape nobody designed."""

    def test_every_drawn_pill_is_the_track_the_widget_paints(self):
        seen = 0
        for frame_key in amazetheme.DIALOG_LAYOUT:
            for box in amazetheme.drawn_boxes(frame_key).get(
                    ("ToggleSwitch", None), ()):
                seen += 1
                self.assertEqual(
                    (ui_helpers.ToggleSwitch.TRACK_W,
                     ui_helpers.ToggleSwitch.TRACK_H), (box[2], box[3]),
                    "%s draws a pill the widget does not paint" % frame_key)
        self.assertGreaterEqual(seen, 10,
                                "the document walk found almost no drawn "
                                "pills, so its silence means nothing")

    def test_the_drawn_text_starts_one_track_and_one_gap_along(self):
        """The Preferences frames only: D02 draws its switch labels in their own column LEFT of the pill, where the widget carries no text of its own."""
        gap = (ui_helpers.ToggleSwitch.TRACK_W
               + ui_helpers.ToggleSwitch.GAP)
        seen = 0
        for frame_key in PREFS_FRAMES:
            frame = amazetheme.DIALOG_LAYOUT[frame_key]
            pills = [(x, y) for kind, x, y, w, h, text in frame["nodes"]
                     if kind == "ToggleSwitch"]
            for kind, x, y, w, h, text in frame["nodes"]:
                if kind != "ToggleSwitch" + TEXT_SUFFIX:
                    continue
                beside = [px for px, py in pills if abs(py - y) <= 3]
                self.assertTrue(
                    beside, "%s draws the label %r with no pill beside it"
                    % (frame_key, text))
                seen += 1
                self.assertEqual(
                    gap, x - beside[0],
                    "%s draws %r %d along from its pill, not %d"
                    % (frame_key, text, x - beside[0], gap))
        self.assertGreaterEqual(seen, 10)

    def test_a_textless_switch_hints_exactly_the_track(self):
        """The drawn D02 pills sit flush at the column's right edge, so the hint carries no slack after the track when there is no text to separate."""
        switch = ui_helpers.ToggleSwitch()
        self.addCleanup(switch.deleteLater)
        self.assertEqual(
            theme.ui_px(ui_helpers.ToggleSwitch.TRACK_W),
            switch.sizeHint().width(),
            "a textless switch hints wider than the pill it paints, so "
            "the painted track lands left of the drawn one")

    def test_a_switch_WITH_text_keeps_its_slack(self):
        """The accept path: the Preferences rows draw text after the pill, where the trailing slack never shows - dropping it there would clip the last glyph."""
        switch = ui_helpers.ToggleSwitch("Debug Mode")
        self.addCleanup(switch.deleteLater)
        metrics = switch.fontMetrics().horizontalAdvance("Debug Mode")
        self.assertGreater(
            switch.sizeHint().width(),
            theme.ui_px(ui_helpers.ToggleSwitch.TRACK_W)
            + theme.ui_px(ui_helpers.ToggleSwitch.GAP) + metrics,
            "the labelled switch lost the slack its text needs")


class ThePinRefusesRatherThanCrashes(unittest.TestCase):
    """A drawn label renamed in Figma must cost one widget's size, never the dialog that holds it."""

    def test_a_label_the_document_does_not_draw_pins_nothing(self):
        button = QtWidgets.QPushButton("Not A Drawn Label")
        self.addCleanup(button.deleteLater)
        before = button.maximumWidth()
        with mock.patch.object(debug, "event") as recorded:
            ui_helpers.pin_drawn(button, "D04", "QPushButton",
                                 "Not A Drawn Label")
        self.assertEqual(before, button.maximumWidth(),
                         "a label the document does not draw still pinned "
                         "the widget to something")
        self.assertTrue(recorded.called,
                        "the missing box was swallowed - nothing in the "
                        "log would say why the widget kept its own size")

    def test_a_drawn_label_IS_pinned(self):
        """The accept path: a pin that refused everything would leave every dialog at the host font's own sizes."""
        button = QtWidgets.QPushButton("Clear Log")
        self.addCleanup(button.deleteLater)
        ui_helpers.pin_drawn(button, "D08", "QPushButton", "Clear Log")
        self.assertEqual((theme.ui_px(62), theme.ui_px(22)),
                         pinned(self, button))


class PreferencesIsBuiltFromTheDocument(unittest.TestCase):
    """Every button, combo and field on the five tabs takes its size from the frame drawn for that tab."""

    def _dialog(self):
        from amaze.dialogs import prefs_dialog
        prefs = test_support.fixture_prefs(self)
        dialog = prefs_dialog.PrefsDialog(prefs, panel=None)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def _pages(self, dialog):
        return dialog.findChild(QtWidgets.QTabWidget)

    def test_the_declared_numbers_agree_with_each_other(self):
        """The Preferences block states the drawing's geometry one number at a time; these are the two sums that have to hold, and the content column is now built from one of them."""
        self.assertEqual(
            amazetheme.PREFS_FORM_WIDTH - 2 * amazetheme.PREFS_INSET,
            amazetheme.PREFS_CONTENT_WIDTH,
            "the content column and the inset disagree about where a row "
            "ends, and the column is what every page is pinned to")
        self.assertEqual(
            amazetheme.PREFS_INSET + amazetheme.PREFS_LABEL_COL
            + amazetheme.PREFS_LABEL_GAP, amazetheme.PREFS_FIELD_X,
            "the label column plus its gap no longer reaches the field "
            "column, so one of the three is wrong")

    def test_every_pinned_widget_lands_on_its_drawn_x(self):
        """SIZE was pinned and POSITION was not, so a row of pinned widgets ended near its drawn boxes rather than on them: the content column is held to the drawn width, and each gap is the drawn gap. Vertical is Qt's own and the host's tab bar moves it, so only x is checked here."""
        dialog = self._dialog()
        dialog.show()
        self.addCleanup(dialog.hide)
        QtWidgets.QApplication.processEvents()
        tabs = self._pages(dialog)
        checked, wrong = 0, []
        for index, frame_key in enumerate(PREFS_FRAMES):
            tabs.setCurrentIndex(index)
            QtWidgets.QApplication.processEvents()
            page = tabs.widget(index)
            for widget in page.findChildren(QtWidgets.QWidget):
                box = getattr(widget, "drawn_box", None)
                if box is None or not widget.isVisibleTo(page):
                    continue
                checked += 1
                built = widget.mapTo(dialog, widget.rect().topLeft()).x()
                if built != theme.ui_px(box[0]):
                    wrong.append(
                        "%s %s %r at x=%d, drawn at %d"
                        % (frame_key, type(widget).__name__,
                           getattr(widget, "text", lambda: "")(), built,
                           theme.ui_px(box[0])))
        self.assertGreaterEqual(
            checked, 20, "almost nothing was pinned, so this says nothing")
        self.assertEqual([], wrong, "\n  ".join([""] + wrong))

    def test_every_named_button_is_the_drawn_size(self):
        dialog = self._dialog()
        tabs = self._pages(dialog)
        for index, frame_key in enumerate(PREFS_FRAMES):
            page = tabs.widget(index)
            found = {b.text(): b
                     for b in page.findChildren(QtWidgets.QPushButton)}
            for label in PINNED_BUTTONS.get(frame_key, ()):
                with self.subTest(frame=frame_key, button=label):
                    self.assertIn(label, found,
                                  "%s has no button reading %r"
                                  % (frame_key, label))
                    box = amazetheme.drawn_boxes(frame_key)[
                        ("QPushButton", label)]
                    self.assertEqual(
                        (theme.ui_px(box[2]), theme.ui_px(box[3])),
                        pinned(self, found[label]),
                        "%s %r is not the box the document draws"
                        % (frame_key, label))

    def test_the_update_button_is_one_geometry_in_both_readings(self):
        """The button morphs between `Check for Updates` and `Install Update`; the document draws one box, so the geometry may not move with the word."""
        dialog = self._dialog()
        first = pinned(self, dialog._btn_update)
        dialog._set_update_button(True)
        self.assertEqual("Install Update", dialog._btn_update.text())
        self.assertEqual(
            first, pinned(self, dialog._btn_update),
            "the button resized when its label changed, so the offer "
            "reading is a size the document never drew")
        box = amazetheme.drawn_boxes("D08")[
            ("QPushButton", "Check for Updates")]
        self.assertEqual((theme.ui_px(box[2]), theme.ui_px(box[3])), first)

    def test_every_combo_is_the_drawn_width(self):
        dialog = self._dialog()
        for frame_key, wanted in PREFS_COMBOS.items():
            for attribute, width in wanted:
                with self.subTest(frame=frame_key, combo=attribute):
                    combo = getattr(dialog, attribute)
                    self.assertEqual(
                        theme.ui_px(width), combo.minimumWidth(),
                        "%s %s is %d wide, not the drawn %d"
                        % (frame_key, attribute, combo.minimumWidth(),
                           width))
                    self.assertEqual(combo.minimumWidth(),
                                     combo.maximumWidth())

    def test_every_line_edit_is_the_drawn_field_height(self):
        dialog = self._dialog()
        want = theme.ui_px(amazetheme.PREFS_FIELD_H)
        for name in ("line_workdir", "line_cache", "line_test_dir"):
            with self.subTest(field=name):
                field = getattr(dialog, name)
                self.assertEqual(want, field.height(),
                                 "%s is not the drawn field height" % name)

    def test_a_spin_box_keeps_its_own_two_taller_height(self):
        """The accept path: a blanket field height would reach the editor INSIDE a spin box, which the document draws inset by 1 in a box 2 taller."""
        dialog = self._dialog()
        self.assertNotEqual(
            theme.ui_px(amazetheme.PREFS_FIELD_H),
            theme.ui_px(amazetheme.PREFS_SPIN_H),
            "the drawn spin height stopped differing, so this proves "
            "nothing")
        editor = dialog.line_rendersize.findChild(QtWidgets.QLineEdit)
        self.assertIsNotNone(editor, "the spin box has no editor to check")
        self.assertNotEqual(
            editor.minimumHeight(), editor.maximumHeight(),
            "the spin box's own editor was pinned, so the box around it "
            "can no longer draw the 2 the document gives it")

    def test_the_window_is_the_drawn_frame(self):
        dialog = self._dialog()
        self.assertEqual(
            (theme.ui_px(amazetheme.PREFS_FRAME[0]),
             theme.ui_px(amazetheme.PREFS_FRAME[1])),
            (dialog.width(), dialog.height()),
            "Preferences opens at a size the document does not draw")

    def test_every_page_fits_inside_the_drawn_frame(self):
        """The drawn frame is the contract, so a page that wants more is a CLIP - reported here with its arithmetic rather than absorbed by growing the window."""
        dialog = self._dialog()
        tabs = self._pages(dialog)
        bar = max(theme.ui_px(amazetheme.PREFS_TAB_BAR[3]),   # the LIVE strip when the host font draws it taller than the document does, or the budget is looser than the window ▸p/headless-host-font
                  tabs.tabBar().sizeHint().height())
        chrome = 2 * theme.ui_px(amazetheme.PREFS_DIALOG_MARGIN) + bar
        budget = theme.ui_px(amazetheme.PREFS_FRAME[1]) - chrome
        over = []
        for index, frame_key in enumerate(PREFS_FRAMES):
            wants = tabs.widget(index).sizeHint().height()
            if wants > budget:
                over.append(
                    "%s %s wants %d, budget %d (frame %d - margins %d - "
                    "tab bar %d), over by %d"
                    % (frame_key, tabs.tabText(index), wants, budget,
                       theme.ui_px(amazetheme.PREFS_FRAME[1]),
                       2 * theme.ui_px(amazetheme.PREFS_DIALOG_MARGIN),
                       bar, wants - budget))
        self.assertEqual(
            [], over,
            "these Preferences pages do not fit the drawn frame, so the "
            "rows below the fold are clipped:\n  " + "\n  ".join(over))


class EveryDrawnNodeIsBoundOrNamed(unittest.TestCase):
    """THE COMPLETENESS PIN: every node in `DIALOG_LAYOUT` either pins a live widget through the binding, or stands on `DRAWN_EXEMPT` with its reason. Anything else is an element the design draws and the app does not read - which is what the D08 version line was until this walk named it. ▸p/one-design-document"""

    def setUp(self):
        amazetheme.forget_drawn_boxes()
        ui_helpers.forget_drawn_pins()
        self.addCleanup(amazetheme.forget_drawn_boxes)
        self.addCleanup(ui_helpers.forget_drawn_pins)
        build_every_frame(self)
        self.pins = ui_helpers.drawn_pins()

    def _matches(self, match):
        return [(frame_key, node)
                for frame_key, frame in amazetheme.DIALOG_LAYOUT.items()
                for node in frame["nodes"] if match(frame_key, node)]

    def test_every_drawn_node_pins_a_widget_or_is_named(self):
        loose = []
        for frame_key, frame in amazetheme.DIALOG_LAYOUT.items():
            for node in frame["nodes"]:
                if (frame_key,) + node[:3] in self.pins:
                    continue
                if any(match(frame_key, node) for match, _why in DRAWN_EXEMPT):
                    continue
                loose.append("%s %s %dx%d at %d,%d %r"
                             % (frame_key, node[0], node[3], node[4],
                                node[1], node[2], node[5]))
        self.assertEqual(
            [], loose,
            "the design draws these and nothing in the app takes its size "
            "from them - pin each one, or put it on DRAWN_EXEMPT with the "
            "reason it needs no pin:\n  " + "\n  ".join(loose))

    def test_the_walk_really_sees_the_pins(self):
        """A build that pinned nothing would pass the walk above by exempting the whole document. ▸p/vacuous-register"""
        self.assertGreaterEqual(
            len(self.pins), 50,
            "the frames built almost no pins, so the completeness walk's "
            "silence means nothing")
        self.assertEqual(
            {"D06"},
            set(amazetheme.DIALOG_LAYOUT)
            - {frame_key for frame_key, _kind, _x, _y in self.pins},
            "D06 draws only switches and the tab strip, so it is the ONE "
            "frame with nothing to pin - any other frame listed here "
            "built no widget the document reached")

    def test_no_exemption_stands_over_a_node_that_IS_pinned(self):
        """An exemption kept over a pinned node reads as a reason while covering nothing, and would let the pin be deleted without a word."""
        for match, why in DRAWN_EXEMPT:
            with self.subTest(exemption=why):
                for frame_key, node in self._matches(match):
                    self.assertNotIn(
                        (frame_key,) + node[:3], self.pins,
                        "%s %s at %d,%d is pinned AND exempted (%s)"
                        % (frame_key, node[0], node[1], node[2], why))

    def test_every_exemption_still_covers_something(self):
        """An exemption the document no longer draws is a reason for nothing, and the next reader takes it for coverage. ▸p/vacuous-register"""
        for match, why in DRAWN_EXEMPT:
            with self.subTest(exemption=why):
                self.assertTrue(
                    self._matches(match),
                    "nothing in the document matches this exemption any "
                    "more - drop it: %s" % why)


class MovingADrawnNodeMovesTheWidget(unittest.TestCase):
    """THE POINT OF ALL OF IT: a rect resized in Figma, once the document is regenerated, resizes the real widget - proved by resizing one and building the dialog."""

    def setUp(self):
        amazetheme.forget_drawn_boxes()
        self.addCleanup(amazetheme.forget_drawn_boxes)

    def _widened(self, frame_key, kind, at, extra):
        """`DIALOG_LAYOUT` with one rect `extra` wider - the sabotage, standing in for a Figma edit."""
        frame = dict(amazetheme.DIALOG_LAYOUT[frame_key])
        frame["nodes"] = tuple(
            (node[0], node[1], node[2], node[3] + extra, node[4], node[5])
            if (node[0], node[1], node[2]) == (kind,) + at else node
            for node in frame["nodes"])
        return frame

    def test_a_wider_drawn_button_builds_a_wider_button(self):
        from amaze.dialogs import prefs_dialog
        prefs = test_support.fixture_prefs(self)
        frame = self._widened("D04", "QPushButton", (148, 70), 5)
        with mock.patch.dict(amazetheme.DIALOG_LAYOUT, {"D04": frame}):
            amazetheme.forget_drawn_boxes()
            dialog = prefs_dialog.PrefsDialog(prefs, panel=None)
            self.addCleanup(dialog.deleteLater)
            button = [b for b in dialog.findChildren(QtWidgets.QPushButton)
                      if b.text() == "Clean Up Library"][0]
            self.assertEqual(
                theme.ui_px(99 + 5), pinned(self, button)[0],
                "the drawn rect was widened and the built button did not "
                "follow, so the dialog is not reading the document")

    def _prefs_dialog(self):
        from amaze.dialogs import prefs_dialog
        dialog = prefs_dialog.PrefsDialog(
            test_support.fixture_prefs(self), panel=None)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_a_wider_drawn_LABEL_builds_a_wider_label(self):
        """A label, not a button: the D08 version line had no stated width at all, and its 322 was whatever the row happened to leave it."""
        frame = self._widened("D08", "QLabel", (148, 278), 5)
        with mock.patch.dict(amazetheme.DIALOG_LAYOUT, {"D08": frame}):
            amazetheme.forget_drawn_boxes()
            dialog = self._prefs_dialog()
            self.assertEqual(
                theme.ui_px(322 + 5), dialog._lbl_version.maximumWidth(),
                "the drawn version line was widened and the built label "
                "did not follow, so its width is still a coincidence")

    def test_the_version_line_is_found_by_its_WORDS_not_its_number(self):
        """THE MECHANISM: the drawn text carries a sample version and the widget goes on to carry the updater's sentences, so the pin matches the words BEFORE the number - a document redrawn at another version still finds the node."""
        from amaze.dialogs import prefs_dialog
        frame = dict(amazetheme.DIALOG_LAYOUT["D08"])
        frame["nodes"] = tuple(
            node[:5] + (prefs_dialog.VERSION_STEM + "9.9.9",)
            if node[:3] == ("QLabel", 148, 278) else node
            for node in frame["nodes"])
        with mock.patch.dict(amazetheme.DIALOG_LAYOUT, {"D08": frame}):
            amazetheme.forget_drawn_boxes()
            dialog = self._prefs_dialog()
            self.assertEqual(
                theme.ui_px(322), dialog._lbl_version.maximumWidth(),
                "the drawn version number changed and the pin lost the "
                "node, so the line is bound to a number that moves")


class TheSaveFamilyWearsTheDrawnButtons(unittest.TestCase):
    """D09, D13 and D14 all draw OK 31 and Cancel 50, flush right at the field column's edge - one pair, four dialogs. ▸p/save-dialog-rows"""

    def _dialogs(self):
        from amaze.dialogs import (base_dialog, gradient_dialog, save_dialog,
                                   user_dialog)
        return (
            ("D09 SaveDialog",
             save_dialog.SaveDialog(["Metal"], "Metal", name="rocks1")),
            ("D13 NameDialog", base_dialog.NameDialog()),
            ("D13 CategoryDialog", gradient_dialog.CategoryDialog()),
            ("D14 UserPickerDialog",
             user_dialog.UserPickerDialog({"u1": "Plum"})),
        )

    def _shown(self, dialog):
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        QtWidgets.QApplication.processEvents()
        self.addCleanup(dialog.hide)
        return dialog

    def _pair(self, dialog):
        box = dialog._buttons
        return (box.button(QtWidgets.QDialogButtonBox.StandardButton.Ok),
                box.button(QtWidgets.QDialogButtonBox.StandardButton.Cancel))

    def test_both_buttons_are_the_drawn_size(self):
        for label, dialog in self._dialogs():
            with self.subTest(dialog=label):
                shown = self._shown(dialog)
                ok, cancel = self._pair(shown)
                self.assertEqual(
                    (theme.ui_px(amazetheme.SAVE_BUTTON_W[0]),
                     theme.ui_px(amazetheme.SAVE_BUTTON_H)),
                    pinned(self, ok), "%s: OK is not the drawn box" % label)
                self.assertEqual(
                    (theme.ui_px(amazetheme.SAVE_BUTTON_W[1]),
                     theme.ui_px(amazetheme.SAVE_BUTTON_H)),
                    pinned(self, cancel),
                    "%s: Cancel is not the drawn box" % label)

    def test_the_pair_is_drawn_OK_then_Cancel(self):
        """A style may lay Cancel first; the drawing does not, and the dialogs follow the drawing."""
        for label, dialog in self._dialogs():
            with self.subTest(dialog=label):
                shown = self._shown(dialog)
                ok, cancel = self._pair(shown)
                self.assertLess(
                    ok.x(), cancel.x(),
                    "%s draws Cancel before OK, which no frame does"
                    % label)
                self.assertEqual(
                    theme.ui_px(amazetheme.SAVE_BUTTON_GAP),
                    cancel.x() - (ok.x() + ok.width()),
                    "%s: the gap between the pair is not the drawn one"
                    % label)

    def test_a_style_that_lays_Cancel_first_is_put_right(self):
        """THE ANTI-VACUOUS HALF: this host's style already draws OK first, so the forcing branch is never entered by the four dialogs above - a box laid out the other way proves it does what it says. ▸p/vacuous-register"""
        from amaze.dialogs import base_dialog
        dialog = base_dialog.NameDialog()
        self.addCleanup(dialog.deleteLater)
        ok, cancel = self._pair(dialog)
        row = dialog._buttons.layout()
        while row.count():
            row.takeAt(0)
        row.addWidget(cancel)      # the macOS and GNOME button order
        row.addWidget(ok)
        dialog._pin_button_row()
        built = [row.itemAt(i).widget() for i in range(row.count())]
        self.assertEqual([None, ok, cancel], built,
                         "a Cancel-first box was left in the order no "
                         "frame draws")

    def test_the_pair_is_flush_right(self):
        for label, dialog in self._dialogs():
            with self.subTest(dialog=label):
                shown = self._shown(dialog)
                ok, cancel = self._pair(shown)
                box = shown._buttons
                self.assertEqual(
                    box.width(), cancel.x() + cancel.width(),
                    "%s: Cancel does not end at the row's right edge"
                    % label)
                self.assertGreater(
                    ok.x(), 0,
                    "%s: the pair starts at the row's left edge, so it "
                    "is not flush right" % label)

    def test_every_field_is_the_drawn_height(self):
        want = theme.ui_px(amazetheme.SAVE_FIELD_H)
        for label, dialog in self._dialogs():
            with self.subTest(dialog=label):
                shown = self._shown(dialog)
                fields = [w for w in shown.findChildren(QtWidgets.QWidget)
                          if isinstance(w, (QtWidgets.QLineEdit,
                                            QtWidgets.QComboBox))
                          and w.parent() is shown]
                self.assertTrue(fields, "%s built no fields at all" % label)
                for field in fields:
                    self.assertEqual(
                        want, field.height(),
                        "%s draws a %s %dpx tall, not the drawn %d"
                        % (label, type(field).__name__, field.height(),
                           want))

    def test_the_user_picker_is_the_drawn_width(self):
        """D14 is drawn 19 wider than D09 and D13, its label column taking the 19 and its field keeping the family's 276."""
        from amaze.dialogs import user_dialog
        self.assertEqual(amazetheme.D14_WIDTH,
                         user_dialog.UserPickerDialog.FORM_WIDTH)
        self.assertEqual(amazetheme.SAVE_FIELD_WIDTH,
                         user_dialog.UserPickerDialog.FIELD_WIDTH)
        self.assertEqual(
            amazetheme.D14_WIDTH - amazetheme.SAVE_WIDTH,
            amazetheme.D14_LABEL_RIGHT - amazetheme.SAVE_LABEL_RIGHT,
            "the extra width and the wider label column disagree, so the "
            "field column no longer starts where D14 draws it")
        shown = self._shown(user_dialog.UserPickerDialog({"u1": "Plum"}))
        self.assertEqual(theme.ui_px(amazetheme.D14_WIDTH), shown.width())


class TheD01ButtonsWearTheirDeclaredNumbers(unittest.TestCase):
    """`D01_RADIUS` and `D01_BUTTON_PX` were declared and never applied - a design number nothing reads is a number nobody can trust. ▸p/designed-dialog"""

    def _buttons(self):
        dialog = ui_helpers.DesignedDialog(None, title="brushed_steel")
        dialog.add_buttons(amazetheme.BTN_CANCEL, amazetheme.BTN_APPLY)
        self.addCleanup(dialog.deleteLater)
        return dialog.findChildren(QtWidgets.QPushButton)

    def test_each_button_carries_the_drawn_corner(self):
        buttons = self._buttons()
        self.assertEqual(2, len(buttons))
        want = "border-radius: %dpx" % theme.ui_px(amazetheme.D01_RADIUS)
        for button in buttons:
            self.assertIn(
                want, button.styleSheet(),
                "the button does not carry the drawn corner radius")

    def test_each_button_carries_the_drawn_text_size(self):
        for button in self._buttons():
            self.assertEqual(
                theme.ui_px(amazetheme.D01_BUTTON_PX),
                button.font().pixelSize(),
                "the button's text is not the size the page draws")


if __name__ == "__main__":
    unittest.main()
