"""The dialogs READ the drawn document: a node moved or resized in Figma moves the real widget, and a drawn label that gets renamed costs one pin rather than the dialog. ▸p/one-design-document"""

import math
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # BEFORE the app exists: the first module to build the QApplication picks the platform for the whole hython ▸p/first-app-picks-the-platform
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

from amaze import amazetheme  # noqa: E402
from amaze.core import debug  # noqa: E402
from amaze.helpers import theme, ui_helpers  # noqa: E402
from amaze.tests import test_support  # noqa: E402

TEXT_SUFFIX = " ▸ text"

PREFS_FRAMES = ("P01", "P02", "P03a", "P03b", "P04", "P05", "P06")

PINNED_BUTTONS = {    # every text button Preferences takes from the document, written out here so a lost pin fails rather than quietly widening to the host font
    "P01": ("Add", "Clean Up", "Reload", "Show Folder", "Manage", "Rename",
            "Delete", "Default", "Delete Local Cache", "Apply", "Accept"),
    "P05": ("Check for Updates",),
    "P06": ("Check for Updates", "Report a Bug...", "Open Log",
            "Save Log...", "Clear Log"),
}

PREFS_COMBOS = {    # (frame, attribute, drawn width) - the combos each tab builds, in creation order
    "P01": (("cbb_library", 260), ("cbb_library_user", 196)),
    "P02": (("_combo_geo_shading", 165), ("_combo_geo_bg", 165),
            ("cbb_matx_res", 72)),
    "P04": (("_combo_path_style", 105), ("_combo_icon_weight", 145)),
}

UNPAIRED = {}    # a drawn `▸ text` node with no rect of its own kind around it; every one must be named, because the ordinary reading of a missing pair is a document edit that lost the rect

LABEL_RIGHT = {    # where a form label's drawn box ENDS - the label column's right edge, per frame. A QLabel ending anywhere else is a FIELD-side label and has to be pinned, which is what the P06 version line was not
    "D02": (63,),               # the drawn field column less `D02_LABEL_GAP`
    "D11": (63, 378),           # each column's field, less the drawn label gap
    "P01": (amazetheme.PREFS_LABEL_RIGHT,),
    "P02": (amazetheme.PREFS_LABEL_RIGHT,),
    "P03a": (amazetheme.PREFS_LABEL_RIGHT,),
    "P03b": (amazetheme.PREFS_LABEL_RIGHT,),
    "P04": (amazetheme.PREFS_LABEL_RIGHT,),
    "P06": (amazetheme.PREFS_LABEL_RIGHT,),
    "D09": (amazetheme.SAVE_LABEL_RIGHT,),
    "D13": (50,),               # the drawn field less its label gap
}

STRETCHED_FIELDS = {    # frame and kind whose fields fill the column instead of wearing a width
    ("D02", "QLineEdit"), ("D02", "QComboBox", 71, 67),    # Category; the Icon menu is pinned
    ("D11", "QLineEdit"), ("D11", "QComboBox"),
}

LOOSE_LABELS = {    # (frame, kind, x, y) of a label drawn BESIDE or ABOVE its control rather than in a column
    ("D02", "QLabel", 202, 189),
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
    (lambda f, n: f == "P05" and n[0].startswith("add-on "),
     "an add-on's row, built per installed add-on from its package: "
     "test_addon_tab holds each row on the drawn ones"),
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
    (lambda f, n: (f, n[0]) in STRETCHED_FIELDS or (f,) + n[:3] in STRETCHED_FIELDS,
     "D02 and D11 are the frames that RESIZE: their fields fill the "
     "column, and the drawn width is the width at the drawn size"),
    (lambda f, n: n[0] == "CodeEditor",
     "the editor is what D11's resize grows; its drawn height is its floor"),
    (lambda f, n: n[0] in ("CodeEditor ▸ line numbers", "CodeEditor ▸ current line"),
     "PAINTED by the editor from drawn_code_dialog: held by TheCodeDialogStandsOnItsFrame"),
    (lambda f, n: n[0] in ("header band ▸ tab", "icon ▸ add ▸ icon_version_add.svg",
                           "icon ▸ close ▸ icon_tab_close.svg"),
     "D11's version tabs, their × and the +, PAINTED by the rule drawn_code_dialog reads: "
     "held by TheCodeDialogStandsOnItsFrame"),
    (lambda f, n: (f,) + n[:3] in LOOSE_LABELS,
     "drawn at its own text width beside its control; the widget takes "
     "the host font's and yields before the row overflows"),
    (lambda f, n: f.startswith("T"),
     "a tile is PAINTED, not built from widgets: the delegate reads its "
     "spacing through drawn_tile, held by TheTileStandsOnItsFrame"),
    (lambda f, n: f.startswith("L"),
     "the list is painted by Houdini's style and our cell delegates: the "
     "panel reads it through drawn_list, held by TheListStandsOnItsFrame"),
    (lambda f, n: f.startswith("B"),
     "the toolbar is a layout of gaps and self-painted controls: the panel "
     "reads it through drawn_toolbar, held by TheToolbarStandsOnItsFrame"),
    (lambda f, n: f.startswith("S"),
     "the tab strip is PAINTED, not built from widgets: it reads its sizes "
     "through drawn_tabs, held by TheTabStripStandsOnItsFrame"),
    (lambda f, n: f.startswith("G"),
     "the sidebar's rows are drawn by Houdini's style: the panel reads its "
     "sizes through drawn_sidebar, held by TheSidebarStandsOnItsFrame"),
    (lambda f, n: f.startswith("N"),
     "the comments pane is a document and a painted margin: it reads its "
     "sizes through drawn_comments, held by TheCommentsPaneStandsOnItsFrame"),
    (lambda f, n: f in ("D15", "D01") and n[0].startswith("QListWidget ▸ item"),
     "a row is PAINTED by the list's delegate: it reads its sizes through "
     "drawn_list_rows, held by TheManageWindowStandsOnItsFrame and test_versions_dialog"),
    (lambda f, n: f in ("P03a", "P03b") and n[0].startswith("Line "),
     "a line PAINTED along the sub-tab page's top or right edge, wherever "
     "the style puts the page: held by TheShowHidePageWearsItsLines"),
)


def build_every_frame(case):
    """One live dialog per drawn frame, so the binding's pins are the real ones - a frame nothing builds cannot be proven bound."""
    from amaze.dialogs import (base_dialog, code_dialog, icon_dialog,
                               library_dialog, prefs_dialog, save_dialog, versions_dialog)
    built = (
        versions_dialog.VersionsDialog("brushed_steel", [
            {"n": 1, "name": "Version 1", "date": "2026-10-22 10:00"},
            {"n": 2, "name": "Version 2", "date": "2026-10-23 11:00"}], 2),
        icon_dialog.IconDialog(None, 0.0, None, tile_name="rocks1",
                               tile_tags="", categories=["Metal"],
                               tile_category="Metal"),
        prefs_dialog.PrefsDialog(test_support.fixture_prefs(case),
                                 panel=None),
        save_dialog.SaveDialog(["Metal"], "Metal", name="rocks1"),
        code_dialog.CodeDialog(["Metal"]),
        base_dialog.NameDialog(),
        library_dialog.ManageLibrariesDialog(test_support.fixture_prefs(case)),
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


UI_FONT_FILE = ("houdini", "fonts", "SideFX-SourceSansPro-Regular.ttf")    # ▸r/font-sizing
UI_FONT_PX = 12          # the size Houdini draws it at, measured live
BUTTON_CLEARANCE = 4     # per side, so a label never meets the button's edge


def ui_font():
    """Houdini's UI face at its live size, from `$HFS`; headless has no such font ▸r/font-sizing"""
    path = os.path.join(os.environ.get("HFS", ""), *UI_FONT_FILE)
    families = QtGui.QFontDatabase.applicationFontFamilies(
        QtGui.QFontDatabase.addApplicationFont(path))
    if not families:
        return None
    font = QtGui.QFont(families[0])
    font.setPixelSize(UI_FONT_PX)
    return font


def unfit_buttons(font):
    """Every drawn button whose label, in `font`, leaves under `BUTTON_CLEARANCE` a side."""
    metrics = QtGui.QFontMetricsF(font)
    unfit = []
    for frame_key, kind, text in sorted({n[:3] for n in text_nodes("QPushButton")}):
        needed = math.ceil(metrics.horizontalAdvance(text)) + 2 * BUTTON_CLEARANCE
        for box in amazetheme.drawn_repeats(frame_key, kind, text):
            if box[2] < needed:
                unfit.append("%s %r: drawn %s wide, its label needs %d"
                             % (frame_key, text, box[2], needed))
    return unfit


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
        self.assertGreaterEqual(
            len(text_nodes("QPushButton")), 20,
            "the document walk found almost no drawn button labels, so "
            "its silence means nothing")
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

    def test_an_unknown_frame_answers_empty(self):
        self.assertEqual({}, amazetheme.drawn_boxes("D99"))


class EveryDrawnButtonFitsItsLabel(unittest.TestCase):
    """A pinned button narrower than its label cuts it at both ends ▸r/drawn-button-width"""

    def setUp(self):
        amazetheme.forget_drawn_boxes()
        self.addCleanup(amazetheme.forget_drawn_boxes)
        self.font = ui_font()
        self.assertIsNotNone(
            self.font, "Houdini's UI font did not load from $HFS, so no "
            "label could be measured")

    def test_every_drawn_button_fits_its_label(self):
        unfit = unfit_buttons(self.font)
        self.assertEqual(
            [], unfit,
            "these drawn buttons are narrower than their label in "
            "Houdini's face, so the label is cut at both ends:\n  "
            + "\n  ".join(unfit))

    def test_a_narrow_drawn_button_is_caught(self):
        narrow = {"frame": [120, 40], "nodes": [
            ("QPushButton", 10, 10, 40, 22, None),
            ("QPushButton" + TEXT_SUFFIX, 12, 13, 36, 15, "Remove from List")]}
        with mock.patch.dict(amazetheme.DIALOG_LAYOUT, {"ZZ99": narrow}):
            amazetheme.forget_drawn_boxes()
            caught = [line for line in unfit_buttons(self.font)
                      if line.startswith("ZZ99")]
        self.assertEqual(1, len(caught), caught)


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
        labelled = ui_helpers.ToggleSwitch("Debug Mode")    # text after the pill keeps its slack
        self.addCleanup(labelled.deleteLater)
        metrics = labelled.fontMetrics().horizontalAdvance("Debug Mode")
        self.assertGreater(
            labelled.sizeHint().width(),
            theme.ui_px(ui_helpers.ToggleSwitch.TRACK_W)
            + theme.ui_px(ui_helpers.ToggleSwitch.GAP) + metrics,
            "the labelled switch lost the slack its text needs, which "
            "clips the last glyph")


class ThePinRefusesRatherThanCrashes(unittest.TestCase):
    """A drawn label renamed in Figma must cost one widget's size, never the dialog that holds it."""

    def test_a_label_the_document_does_not_draw_pins_nothing(self):
        button = QtWidgets.QPushButton("Not A Drawn Label")
        self.addCleanup(button.deleteLater)
        before = button.maximumWidth()
        with mock.patch.object(debug, "event") as recorded:
            ui_helpers.pin_drawn(button, "P01", "QPushButton",
                                 "Not A Drawn Label")
        self.assertEqual(before, button.maximumWidth(),
                         "a label the document does not draw still pinned "
                         "the widget to something")
        self.assertTrue(recorded.called,
                        "the missing box was swallowed - nothing in the "
                        "log would say why the widget kept its own size")


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
        checked, wrong = 0, []
        for frame_key in PREFS_FRAMES:
            page = dialog.show_frame(frame_key)
            QtWidgets.QApplication.processEvents()
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
        for frame_key in PREFS_FRAMES:
            page = dialog.frame_page(frame_key)
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
        box = amazetheme.drawn_boxes("P06")[
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
        for name in ("line_cache", "line_test_dir"):
            with self.subTest(field=name):
                field = getattr(dialog, name)
                self.assertEqual(want, field.height(),
                                 "%s is not the drawn field height" % name)
        self.assertNotEqual(    # the editor INSIDE a spin box sits in a box drawn 2 taller
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

    def test_every_page_is_one_drawn_frame(self):
        from amaze.dialogs import prefs_dialog
        dialog = self._dialog()
        self.assertEqual(PREFS_FRAMES, prefs_dialog.PREFS_FRAMES)
        self.assertEqual(
            len(PREFS_FRAMES), len(dialog._steps_to_pages()),
            "Preferences builds a different number of pages than it has "
            "drawn frames, so the pins land on the wrong pages")

    def test_show_hide_is_the_two_drawn_sub_tabs(self):
        """P03a and P03b: a Renderer and a Sections sub-tab, each holding its own switches."""
        dialog = self._dialog()
        dialog.show()
        self.addCleanup(dialog.hide)
        QtWidgets.QApplication.processEvents()
        tabs = self._pages(dialog)
        names = [tabs.tabText(index) for index in range(tabs.count())]
        sub_tabs = tabs.widget(names.index("Show/Hide")).findChild(
            QtWidgets.QTabWidget)
        self.assertIsNotNone(sub_tabs, "Show/Hide holds no sub-tabs")
        bar = amazetheme.PREFS_SUBTAB_BAR
        for frame_key in ("P03a", "P03b"):
            nodes = amazetheme.DIALOG_LAYOUT[frame_key]["nodes"]
            self.assertIn(("QTabBar",) + bar + (None,), nodes,
                          "%s draws the sub-tab strip somewhere else" % frame_key)
            drawn = [node[5] for node in sorted(nodes, key=lambda n: n[1])
                     if node[0].startswith("QTabBar::tab") and node[5]
                     and inside(node, bar)]
            self.assertEqual(
                drawn, [sub_tabs.tabText(i) for i in range(sub_tabs.count())],
                "the sub-tabs are not the ones %s draws" % frame_key)
        for frame_key, boxes in (("P03a", dialog._renderer_boxes),
                                 ("P03b", dialog._section_boxes)):
            with self.subTest(frame=frame_key):
                page = dialog.show_frame(frame_key)
                QtWidgets.QApplication.processEvents()
                built = sorted(page.findChildren(ui_helpers.ToggleSwitch),
                               key=lambda b: b.mapTo(page, b.rect().topLeft()).y())
                drawn = [node[5] for node in sorted(
                    amazetheme.DIALOG_LAYOUT[frame_key]["nodes"],
                    key=lambda n: n[2]) if node[0] == "ToggleSwitch" + TEXT_SUFFIX]
                self.assertEqual(drawn, [box.text() for box in built],
                                 "%s's switches are not the drawn ones" % frame_key)
                self.assertEqual(set(boxes.values()), set(built))
        strip, main = sub_tabs.tabBar(), tabs.tabBar()
        at = strip.mapTo(dialog, strip.rect().topLeft())
        main_at = main.mapTo(dialog, main.rect().topLeft())
        main_x, main_y, _w, main_h = amazetheme.PREFS_TAB_BAR
        self.assertEqual(theme.ui_px(bar[0] - main_x), at.x() - main_at.x(),
                         "the sub-tab strip does not start under the main strip")
        self.assertEqual(theme.ui_px(bar[1] - main_y - main_h),
                         at.y() - main_at.y() - main.height(),
                         "the sub-tab strip is not the drawn gap below the main strip")

    def test_every_page_fits_inside_the_drawn_frame(self):
        """The drawn frame is the contract, so a page that wants more is a CLIP - reported here with its arithmetic rather than absorbed by growing the window."""
        dialog = self._dialog()
        tabs = self._pages(dialog)
        bar = max(theme.ui_px(amazetheme.PREFS_TAB_BAR[3]),   # the LIVE strip when the host font draws it taller than the document does, or the budget is looser than the window ▸p/headless-host-font
                  tabs.tabBar().sizeHint().height())
        chrome = 2 * theme.ui_px(amazetheme.PREFS_DIALOG_MARGIN) + bar
        budget = theme.ui_px(amazetheme.PREFS_FRAME[1]) - chrome
        over = []
        for index in range(tabs.count()):
            wants = tabs.widget(index).sizeHint().height()
            if wants > budget:
                over.append(
                    "%s wants %d, budget %d (frame %d - margins %d - "
                    "tab bar %d), over by %d"
                    % (tabs.tabText(index), wants, budget,
                       theme.ui_px(amazetheme.PREFS_FRAME[1]),
                       2 * theme.ui_px(amazetheme.PREFS_DIALOG_MARGIN),
                       bar, wants - budget))
        self.assertEqual(
            [], over,
            "these Preferences pages do not fit the drawn frame, so the "
            "rows below the fold are clipped:\n  " + "\n  ".join(over))


class EveryDrawnNodeIsBoundOrNamed(unittest.TestCase):
    """THE COMPLETENESS PIN: every node in `DIALOG_LAYOUT` either pins a live widget through the binding, or stands on `DRAWN_EXEMPT` with its reason. Anything else is an element the design draws and the app does not read - which is what the P06 version line was until this walk named it. ▸p/one-design-document"""

    def setUp(self):
        amazetheme.forget_drawn_boxes()
        ui_helpers.forget_drawn_pins()
        self.addCleanup(amazetheme.forget_drawn_boxes)
        self.addCleanup(ui_helpers.forget_drawn_pins)
        build_every_frame(self)
        self.pins = ui_helpers.drawn_pins()

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
            {"P03a", "P03b", "T01", "T05", "T08", "L01", "B01", "S01", "G01", "N01",
             "N01B"},
            set(amazetheme.DIALOG_LAYOUT)
            - {frame_key for frame_key, _kind, _x, _y in self.pins},
            "P03a and P03b draw only switches and tab strips, and the panel's areas "
            "are read through their own drawn_* - any other frame listed here "
            "built no widget the document reached")


class TheCodeDialogStandsOnItsFrame(unittest.TestCase):
    """D11 opens at its drawn size, every part where the frame draws it. ▸p/one-design-document"""

    def setUp(self):
        from amaze.dialogs import code_dialog
        self.dialog = code_dialog.CodeDialog(["Metal"], name="helper", saved=True)
        self.addCleanup(self.dialog.deleteLater)
        self.dialog.show()
        QtWidgets.QApplication.processEvents()

    def _at(self, widget):
        corner = widget.mapTo(self.dialog, QtCore.QPoint(0, 0))
        return (corner.x(), corner.y(), widget.width(), widget.height())

    @staticmethod
    def _drawn(name):
        return [tuple(theme.ui_px(v) for v in n[1:5])
                for n in amazetheme.DIALOG_LAYOUT["D11"]["nodes"] if n[0] == name]

    def test_the_window_opens_at_the_frame(self):
        self.assertEqual(tuple(theme.ui_px(v) for v in amazetheme.DIALOG_LAYOUT["D11"]["frame"]),
                         (self.dialog.width(), self.dialog.height()))

    def test_every_part_sits_on_its_drawn_box(self):
        d = self.dialog
        for name, widgets in (
                ("CodeEditor", (d._editor,)),
                ("QPushButton", (d._apply_button, d._cancel_button)),
                ("QLineEdit", (d._line_name, d._line_tags)),
                ("QComboBox", (d._combo_category, d._combo_lang))):
            with self.subTest(part=name):
                self.assertEqual(self._drawn(name), [self._at(w) for w in widgets])

    def _two_tabs(self, long_name=""):
        from amaze.dialogs import code_dialog
        dialog = code_dialog.CodeDialog(
            ["Metal"], name=long_name or "[name of Version]", saved=True, active=2,
            versions=[{"n": 1, "name": "[name of Version]"}, {"n": 2, "name": "x"}],
            load_version=lambda number: "// %d" % number)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        dialog._show_version(1)
        QtWidgets.QApplication.processEvents()
        return dialog

    def test_the_tabs_follow_the_drawn_rule(self):
        """As wide as name and ×, a drawn gap apart, the × flush right, the + right after."""
        dialog = self._two_tabs()
        bar, drawn = dialog._tabbar, amazetheme.drawn_code_dialog()
        boxes = bar.boxes()
        inset, close_w = theme.ui_px(drawn["tab_text"][0]), theme.ui_px(drawn["tab_close"][0])
        width = inset + math.ceil(QtGui.QFontMetricsF(bar.font()).horizontalAdvance(
            "[name of Version]")) + close_w
        self.assertEqual([width, width], [box.width() for box in boxes])
        self.assertEqual(theme.ui_px(drawn["tab_gap"]), boxes[1].left() - boxes[0].right())
        self.assertEqual([box.right() for box in boxes],
                         [bar.close_box(box).right() for box in boxes], "a × is not flush right")
        plus = dialog._plus.mapTo(bar.parentWidget(), QtCore.QPoint(0, 0)).x()
        self.assertEqual(bar.x() + math.ceil(boxes[-1].right()) + theme.ui_px(drawn["plus_gap"]),
                         plus, "the + does not follow the last tab")

    def test_a_long_name_stops_at_the_tab_limit(self):
        dialog = self._two_tabs(long_name="a version name far too long for any tab " * 3)
        self.assertEqual(theme.ui_px(amazetheme.CODE_TAB_MAX_W),
                         dialog._tabbar.boxes()[0].width())

    def test_the_front_tab_is_lit_and_rounded_at_its_top_alone(self):
        dialog = self._two_tabs()
        band = dialog.findChild(QtWidgets.QWidget, "amaze_header_band")
        bar = dialog._tabbar
        shot = band.grab().toImage()
        front, back = (box.translated(bar.x(), bar.y()).toRect() for box in bar.boxes()[::-1])
        lit = QtGui.QColor(amazetheme.CODE_TAB).rgb()
        self.assertEqual(
            (False, False, True, True, True),
            tuple(shot.pixel(x, y) == lit for x, y in (
                (front.left(), front.top()), (front.right(), front.top()),
                (front.left(), front.bottom()), (front.right(), front.bottom()),
                (front.left() + 4, front.top()))),
            "the front tab is not rounded at its top corners alone, as drawn")
        self.assertEqual(QtGui.QColor(amazetheme.CODE_BAND).rgb(),
                         shot.pixel(back.left() + 4, back.top() + 1),
                         "a tab behind the front one is not the band's own colour")

    def test_the_window_behind_the_form_is_the_drawn_ground(self):
        shot = self.dialog.grab().toImage()
        ratio = shot.devicePixelRatio()
        name = self._drawn("QLineEdit")[0]    # beside it, on the Name label's bare left end
        x, y = theme.ui_px(12), name[1] + name[3] // 2
        self.assertEqual(QtGui.QColor(amazetheme.CODE_GROUND).name(),
                         QtGui.QColor(shot.pixel(int(x * ratio), int(y * ratio))).name(),
                         "the window behind the form is not the drawn ground")

    def test_the_current_line_sits_on_its_letters(self):
        """Centred between cap top and descender, in Houdini's code face, as drawn."""
        from amaze.dialogs import code_dialog
        face = os.path.join(os.environ.get("HFS", ""), "houdini", "fonts",
                            "SideFX-SourceCodePro-Regular.ttf")
        if amazetheme.CODE_FONT[0] not in QtGui.QFontDatabase.families():
            if not os.path.exists(face):
                self.skipTest("no Houdini code face at %s" % face)
            QtGui.QFontDatabase.addApplicationFont(face)
        editor = code_dialog.CodeEditor("gggg\nHHHH")
        self.addCleanup(editor.deleteLater)
        editor.resize(400, 120)
        editor.show()
        editor.setTextCursor(QtGui.QTextCursor(editor.document().findBlockByNumber(1)))
        QtWidgets.QApplication.processEvents()
        shot = editor.viewport().grab().toImage()
        ground, probe = shot.pixel(shot.width() - 3, shot.height() - 3), shot.width() - 30

        def rows(number, inked):
            block = editor.document().findBlockByNumber(number)
            top = int(editor.blockBoundingGeometry(block).translated(editor.contentOffset()).top())
            high = int(editor.blockBoundingRect(block).height())
            return top, [y - top for y in range(top, top + high) if inked(y)]

        _top, descender = rows(0, lambda y: any(shot.pixel(x, y) != ground for x in range(2, 40)))
        top, letters = rows(1, lambda y: any(shot.pixel(x, y) not in (ground, shot.pixel(probe, y))
                                             for x in range(2, 40)))
        band = [y - top for y in range(shot.height()) if shot.pixel(probe, y) != ground]
        self.assertLessEqual(abs((band[0] + band[-1] + 1) - (letters[0] + descender[-1] + 1)) / 2.0,
                             1.0, "the band sits off the letters: band %s, cap %d, descender %d"
                             % ((band[0], band[-1]), letters[0], descender[-1]))

    def test_versions_off_takes_the_plus_away_and_off_looks_off(self):
        from amaze.dialogs import code_dialog
        off = code_dialog.CodeDialog(["Metal"], name="helper", saved=True, versions_on=False)
        fresh = code_dialog.CodeDialog(["Metal"], name="", saved=False)
        for dialog in (off, fresh):
            self.addCleanup(dialog.deleteLater)
        self.assertTrue(off._plus.isHidden(), "Versions is off and the + is still there")
        self.assertEqual((False, False), (fresh._plus.isHidden(), fresh._plus.isEnabled()))
        icon = fresh._plus.icon()
        self.assertNotEqual(icon.pixmap(22, 22, QtGui.QIcon.Mode.Normal).toImage(),
                            icon.pixmap(22, 22, QtGui.QIcon.Mode.Disabled).toImage(),
                            "the + looks the same off as on")

    def test_the_code_starts_where_the_drawn_text_does(self):
        editor = self.dialog._editor
        drawn = amazetheme.drawn_code_dialog()
        self.assertEqual(theme.ui_px(drawn["text_x"]), editor.line_number_area_width(),
                         "the line numbers' gutter is not the drawn width")
        self.assertEqual(0, editor.document().documentMargin(),
                         "a document margin moves the code off its drawn place")


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
        frame = self._widened("P01", "QPushButton", (148, 70), 5)
        with mock.patch.dict(amazetheme.DIALOG_LAYOUT, {"P01": frame}):
            amazetheme.forget_drawn_boxes()
            dialog = prefs_dialog.PrefsDialog(prefs, panel=None)
            self.addCleanup(dialog.deleteLater)
            button = [b for b in dialog.findChildren(QtWidgets.QPushButton)
                      if b.text() == "Clean Up"][0]
            self.assertEqual(
                theme.ui_px(63 + 5), pinned(self, button)[0],
                "the drawn rect was widened and the built button did not "
                "follow, so the dialog is not reading the document")

    def test_a_wider_drawn_gap_builds_a_wider_gap(self):
        from amaze.dialogs import base_dialog
        frame = dict(amazetheme.DIALOG_LAYOUT["D13"])
        frame["nodes"] = tuple(    # Cancel and its label 4 further right
            (node[0], node[1] + 4) + node[2:]
            if node[0].startswith("QPushButton") and node[1] >= 220 else node
            for node in frame["nodes"])
        with mock.patch.dict(amazetheme.DIALOG_LAYOUT, {"D13": frame}):
            amazetheme.forget_drawn_boxes()
            dialog = base_dialog.NameDialog()
            self.addCleanup(dialog.deleteLater)
            dialog.show()
            QtWidgets.QApplication.processEvents()
            self.addCleanup(dialog.hide)
            box = dialog._buttons
            ok = box.button(QtWidgets.QDialogButtonBox.StandardButton.Ok)
            cancel = box.button(
                QtWidgets.QDialogButtonBox.StandardButton.Cancel)
            self.assertEqual(
                theme.ui_px(6 + 4), cancel.x() - (ok.x() + ok.width()),
                "the drawn gap was widened and the built pair did not "
                "follow, so the gap is still a constant")

    def _prefs_dialog(self):
        from amaze.dialogs import prefs_dialog
        dialog = prefs_dialog.PrefsDialog(
            test_support.fixture_prefs(self), panel=None)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_a_wider_drawn_LABEL_builds_a_wider_label(self):
        """A label, not a button: the P06 version line had no stated width at all, and its 322 was whatever the row happened to leave it."""
        frame = self._widened("P06", "QLabel", (148, 274), 5)
        with mock.patch.dict(amazetheme.DIALOG_LAYOUT, {"P06": frame}):
            amazetheme.forget_drawn_boxes()
            dialog = self._prefs_dialog()
            self.assertEqual(
                theme.ui_px(322 + 5), dialog._lbl_version.maximumWidth(),
                "the drawn version line was widened and the built label "
                "did not follow, so its width is still a coincidence")

        from amaze.dialogs import prefs_dialog    # the pin matches the WORDS, before a sample number
        frame = dict(amazetheme.DIALOG_LAYOUT["P06"])
        frame["nodes"] = tuple(
            node[:5] + (prefs_dialog.VERSION_STEM + "9.9.9",)
            if node[:3] == ("QLabel", 148, 274) else node
            for node in frame["nodes"])
        with mock.patch.dict(amazetheme.DIALOG_LAYOUT, {"P06": frame}):
            amazetheme.forget_drawn_boxes()
            dialog = self._prefs_dialog()
            self.assertEqual(
                theme.ui_px(322), dialog._lbl_version.maximumWidth(),
                "the drawn version number changed and the pin lost the "
                "node, so the line is bound to a number that moves")


class TheShowHidePageWearsItsLines(unittest.TestCase):
    """P03a and P03b draw a line along the sub-tab page's top and down its right edge."""

    def test_the_drawn_lines_frame_the_drawn_page(self):
        bar = amazetheme.PREFS_SUBTAB_BAR
        for frame_key in ("P03a", "P03b"):
            nodes = {n[0]: n for n in amazetheme.DIALOG_LAYOUT[frame_key]["nodes"]}
            top, side = nodes["Line 1"], nodes["Line 2"]
            with self.subTest(frame=frame_key):
                self.assertEqual(bar[0], top[1], "the top line does not start under the strip")
                self.assertEqual(top[1] + top[3], side[1],
                                 "the top line does not end where the side line stands")
                self.assertEqual(bar[1] + bar[3], side[2],
                                 "the side line does not start under the strip")

    def test_the_lines_run_along_the_page_top_and_right(self):
        from amaze.dialogs import prefs_dialog
        dialog = prefs_dialog.PrefsDialog(test_support.fixture_prefs(self), panel=None)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.addCleanup(dialog.hide)
        dialog.show_frame("P03a")
        QtWidgets.QApplication.processEvents()
        lines = dialog._page_lines
        stack = lines.parentWidget().findChild(QtWidgets.QStackedWidget)
        self.assertEqual(stack.geometry(), lines.geometry(), "the lines do not lie over the page")
        picture = lines.grab().toImage()
        ink = QtGui.QColor(amazetheme.PREFS_PAGE_LINE_INK).rgb()
        right, bottom = picture.width() - 1, picture.height() - 1
        for x, y in ((0, 0), (right // 2, 0), (right, 0), (right, bottom // 2), (right, bottom)):
            self.assertEqual(ink, picture.pixel(x, y), "no line at %d,%d" % (x, y))
        self.assertNotEqual(ink, picture.pixel(right // 2, bottom // 2),
                            "the page is filled, not lined")


class TheFormFamilyStandsOnItsFrame(unittest.TestCase):
    """D09 and D13 take every margin and gap from their frames. ▸r/form-from-frame"""

    def _built(self):
        from amaze.dialogs import base_dialog, save_dialog
        return (
            ("D09", save_dialog.SaveDialog(
                ["Metal"], "Metal", name="rocks1",
                sections=(("material", "Material"), ("cop", "Node")),
                section="material", language="VEX",
                language_sections=("code",))),
            ("D13", base_dialog.NameDialog()),
        )

    @staticmethod
    def _box(widget, dialog):
        corner = widget.mapTo(dialog, widget.rect().topLeft())
        return (corner.x(), corner.y(), widget.width(), widget.height())

    def test_fields_buttons_and_window_land_where_drawn(self):
        for key, dialog in self._built():
            with self.subTest(frame=key):
                self.addCleanup(dialog.deleteLater)
                dialog.show()
                QtWidgets.QApplication.processEvents()
                self.addCleanup(dialog.hide)
                px = lambda box: tuple(theme.ui_px(n) for n in box)    # noqa: E731
                self.assertEqual(
                    px(amazetheme.DIALOG_LAYOUT[key]["frame"]),
                    (dialog.width(), dialog.height()))
                boxes = amazetheme.drawn_boxes(key)
                drawn = sorted(boxes.get(("QLineEdit", None), ())
                               + boxes.get(("QComboBox", None), ()),
                               key=lambda box: box[1])
                form = dialog._form
                built = [form.itemAt(row, QtWidgets.QFormLayout.ItemRole.FieldRole)
                         for row in range(form.rowCount())]
                built = [self._box(item.widget(), dialog) for item in built
                         if item is not None and item.widget() is not None]
                self.assertEqual([px(box) for box in drawn], built)
                ok = dialog._buttons.button(
                    QtWidgets.QDialogButtonBox.StandardButton.Ok)
                self.assertEqual(px(boxes[("QPushButton", "OK")]),
                                 self._box(ok, dialog))


class TheSaveFamilyWearsTheDrawnButtons(unittest.TestCase):
    """D09 and D13 draw OK and Cancel flush right at the field edge. ▸p/save-dialog-rows"""

    def _dialogs(self):
        from amaze.dialogs import base_dialog, gradient_dialog, save_dialog
        return (
            ("D09 SaveDialog",
             save_dialog.SaveDialog(["Metal"], "Metal", name="rocks1")),
            ("D13 NameDialog", base_dialog.NameDialog()),
            ("D13 CategoryDialog", gradient_dialog.CategoryDialog()),
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
                boxes = amazetheme.drawn_boxes(shown.FRAME_KEY)
                for button, word in ((ok, "OK"), (cancel, "Cancel")):
                    box = boxes[("QPushButton", word)]
                    self.assertEqual(
                        (theme.ui_px(box[2]), theme.ui_px(box[3])),
                        pinned(self, button),
                        "%s: %s is not the drawn box" % (label, word))
                self.assertLess(    # a style may lay Cancel first; the drawing does not
                    ok.x(), cancel.x(),
                    "%s draws Cancel before OK, which no frame does"
                    % label)
                self.assertEqual(
                    theme.ui_px(amazetheme.drawn_pair_gap(shown.FRAME_KEY)),
                    cancel.x() - (ok.x() + ok.width()),
                    "%s: the gap between the pair is not the drawn one"
                    % label)
                self.assertEqual(
                    shown._buttons.width(), cancel.x() + cancel.width(),
                    "%s: Cancel does not end at the row's right edge"
                    % label)
                self.assertGreater(
                    ok.x(), 0,
                    "%s: the pair starts at the row's left edge, so it "
                    "is not flush right" % label)

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


if __name__ == "__main__":
    unittest.main()
