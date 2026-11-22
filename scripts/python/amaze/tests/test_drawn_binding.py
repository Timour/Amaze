"""Dialogs read the drawn document: moving a node in Figma moves the widget ▸p/one-design-document"""

import math
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # before the app exists ▸p/first-app-picks-the-platform
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

from amaze import amazetheme  # noqa: E402
from amaze.core import debug  # noqa: E402
from amaze.helpers import theme, ui_helpers  # noqa: E402
from amaze.tests import test_support  # noqa: E402

TEXT_SUFFIX = " ▸ text"


def _houdini_ui_font():
    """Houdini's UI font at 12 px from $HFS; headless the placeholder is Courier ▸r/windows-files"""
    path = os.path.join(hou.getenv("HFS") or "", "houdini", "fonts",
                        "SideFX-SourceSansPro-Regular.ttf")
    families = QtGui.QFontDatabase.applicationFontFamilies(
        QtGui.QFontDatabase.addApplicationFont(path))
    if not families:
        raise unittest.SkipTest("Houdini's UI font is not at %s" % path)
    font = QtGui.QFont(families[0])
    font.setPixelSize(theme.ui_px(12))
    return font

UNPAIRED = {}    # a drawn `▸ text` node with no rect of its own kind around it; every one is named

LABEL_RIGHT = {    # where a form label's drawn box ends, per frame; a QLabel ending elsewhere must be pinned
    "D02": (63,),               # the drawn field column less `D02_LABEL_GAP`
    "D11": (63, 378),           # each column's field, less the drawn label gap
    "D09": (amazetheme.SAVE_LABEL_RIGHT,),
    "D13": (50,),               # the drawn field less its label gap
}

STRETCHED_FIELDS = {    # frame and kind whose fields fill the column instead of having a fixed width
    ("D02", "QLineEdit"), ("D02", "QComboBox", 71, 43),    # Category; the Image menu is pinned
    ("D11", "QLineEdit"), ("D11", "QComboBox"),
}

LOOSE_LABELS = {    # (frame, kind, x, y) of a label drawn BESIDE or ABOVE its control rather than in a column
    ("D02", "QLabel", 202, 165),
    ("D02", "QLabel", 212, 196),
}


def plain_rects(frame_key, kind):
    return amazetheme.drawn_boxes(frame_key).get((kind, None), ())


def inside(node, box):
    """The node's drawn rect is inside `box`."""
    return bool(box) and (box[0] <= node[1] and box[1] <= node[2]
                          and box[0] + box[2] >= node[1] + node[3]
                          and box[1] + box[3] >= node[2] + node[4])


def band_box(frame_key):
    found = plain_rects(frame_key, "header band")
    return found[0] if found else ()


DRAWN_EXEMPT = (    # (does this node need no pin, why): every other drawn node must pin a live widget
    (lambda f, n: n[0].endswith(TEXT_SUFFIX),
     "sample text drawn INSIDE a rect; the rect is what the widget wears"),
    (lambda f, n: n[0].startswith("QTabBar"),
     "the tab strip and its chips: Qt lays the bar out from the tab "
     "labels, and nothing in the app places a tab"),
    (lambda f, n: n[0] == "QScrollBar",
     "Qt's own, shown and hidden by the view it belongs to"),
    (lambda f, n: f.startswith("P"),
     "Preferences is Houdini's own QML window, laid out by Houdini's prefs rows; "
     "its P frames are to be drawn again to match it"),
    (lambda f, n: n[0] == "header band",
     "a painted strip the frame's full width, `HEADER_BAND_H` tall"),
    (lambda f, n: n[0] == "QLabel" and inside(n, band_box(f)),
     "the band's own text, placed and sized by `ui_helpers.header_band`"),
    (lambda f, n: n[0].startswith("icon grid"),
     "a drawing device standing in for the `D02_CELL` cells the chooser "
     "builds itself, and the note that says so"),
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
     "PAINTED by the editor from drawn_code_dialog: held by TheCodeDialogMatchesItsDesignFrame"),
    (lambda f, n: n[0] in ("header band ▸ tab", "icon ▸ add ▸ icon_version_add.svg",
                           "icon ▸ close ▸ icon_tab_close.svg"),
     "D11's version tabs, their × and the +, PAINTED by the rule drawn_code_dialog reads: "
     "held by TheCodeDialogMatchesItsDesignFrame"),
    (lambda f, n: (f,) + n[:3] in LOOSE_LABELS,
     "drawn at its own text width beside its control; the widget takes "
     "the host font's and yields before the row overflows"),
    (lambda f, n: f.startswith("T"),
     "a tile is PAINTED, not built from widgets: the delegate reads its "
     "spacing through drawn_tile, held by TheTileMatchesItsDesignFrame"),
    (lambda f, n: f.startswith("L"),
     "the list is painted by Houdini's style and our cell delegates: the "
     "panel reads it through drawn_list, held by TheListMatchesItsDesignFrame"),
    (lambda f, n: f.startswith("B"),
     "the toolbar is a layout of gaps and self-painted controls: the panel "
     "reads it through drawn_toolbar, held by TheToolbarMatchesFrameB01"),
    (lambda f, n: f.startswith("S"),
     "the tab strip is a tab bar drawn by Houdini's style: it reads its height "
     "and icons through drawn_tabs, held by TheTabStripMatchesItsDesignFrame"),
    (lambda f, n: f.startswith("G"),
     "the sidebar's rows are drawn by Houdini's style: the panel reads its "
     "sizes through drawn_sidebar, held by TheSidebarMatchesItsDesignFrame"),
    (lambda f, n: f in ("N01", "N01B"),
     "the comments pane is a document and a painted margin: it reads its "
     "sizes through drawn_comments, held by TheCommentsPaneMatchesItsDesignFrame"),
    (lambda f, n: f == "N02",
     "the info pane's rows are drawn by Houdini's style: it reads its sizes through "
     "drawn_info, held by test_info_panel ▸ TheInfoPaneMatchesItsDesignFrame"),
    (lambda f, n: f in ("D15", "D01") and n[0].startswith("QListWidget ▸ "),
     "a row is drawn by Houdini's style, not pixel-matched: the list reads its column "
     "from drawn_list_rows, held by TheManageWindowMatchesItsDesignFrame and test_versions_dialog"),
)


def build_every_frame(case):
    """One live dialog per drawn frame, so the pinned sizes checked are the real ones."""
    from amaze.dialogs import (base_dialog, code_dialog, icon_dialog,
                               library_dialog, save_dialog, versions_dialog)
    built = (
        versions_dialog.VersionsDialog("brushed_steel", [
            {"n": 1, "name": "Version 1", "date": "2026-10-22 10:00"},
            {"n": 2, "name": "Version 2", "date": "2026-10-23 11:00"}], 2),
        icon_dialog.IconDialog(None, 0.0, None, tile_name="rocks1",
                               tile_tags="", categories=["Metal"],
                               tile_category="Metal"),
        save_dialog.SaveDialog(["Metal"], "Metal", name="rocks1"),
        code_dialog.CodeDialog(["Metal"]),
        base_dialog.NameDialog(),
        library_dialog.ManageLibrariesDialog(test_support.fixture_prefs(case)),
    )
    for dialog in built:
        case.addCleanup(dialog.deleteLater)
    return built


def text_nodes(kind_wanted):
    """(frame, kind, text, box) for every drawn `<Kind> ▸ text` node of one kind, document-wide."""
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
    """The widget's pinned (w, h), asserting it is pinned: `width()` gives the last layout's."""
    case.assertEqual(
        (widget.minimumWidth(), widget.minimumHeight()),
        (widget.maximumWidth(), widget.maximumHeight()),
        "%s is not pinned at all" % widget)
    return widget.minimumWidth(), widget.minimumHeight()


class TheDocumentPairsEveryDrawnButton(unittest.TestCase):
    """`drawn_boxes` reads `DIALOG_LAYOUT` and pairs each drawn label with its rect."""

    def setUp(self):
        amazetheme.forget_drawn_boxes()
        self.addCleanup(amazetheme.forget_drawn_boxes)

    def test_every_drawn_button_label_finds_its_rect(self):
        self.assertGreaterEqual(
            len(text_nodes("QPushButton")), 20,
            "the document walk found almost no drawn button labels, so "
            "an empty result proves nothing")
        missing = []
        for frame_key, kind, text, box in text_nodes("QPushButton"):
            if (frame_key, kind, text) in UNPAIRED:
                continue
            if amazetheme.drawn_boxes(frame_key).get((kind, text)) is None:
                missing.append("%s %s %r at %s" % (frame_key, kind, text, box))
        self.assertEqual(
            [], missing,
            "these drawn button labels are inside no rect of their own "
            "kind, so nothing can be pinned from them:\n  "
            + "\n  ".join(missing))

    def test_an_unknown_frame_returns_empty(self):
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
    """`ToggleSwitch`'s own numbers agree with the pills the document draws."""

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
                                "pills, so an empty result proves nothing")

    def test_a_textless_switch_hints_exactly_the_track(self):
        """D02 pills are flush right, so a textless switch's size hint ends at the track."""
        switch = ui_helpers.ToggleSwitch()
        self.addCleanup(switch.deleteLater)
        self.assertEqual(
            theme.ui_px(ui_helpers.ToggleSwitch.TRACK_W),
            switch.sizeHint().width(),
            "a textless switch's size hint is wider than the pill it paints, so "
            "the painted track is left of the drawn one")
        labelled = ui_helpers.ToggleSwitch("Debug Mode")    # text after the pill keeps its slack
        self.addCleanup(labelled.deleteLater)
        metrics = labelled.fontMetrics().horizontalAdvance("Debug Mode")
        self.assertGreater(
            labelled.sizeHint().width(),
            theme.ui_px(ui_helpers.ToggleSwitch.TRACK_W)
            + theme.ui_px(ui_helpers.ToggleSwitch.GAP) + metrics,
            "the labelled switch lost the slack its text needs, which "
            "clips the last glyph")


class AnUndrawnLabelLeavesTheWidgetUnsizedAndIsLogged(unittest.TestCase):
    """A drawn label renamed in Figma leaves one widget unsized; it never breaks the dialog."""

    def test_a_label_the_document_does_not_draw_pins_nothing(self):
        button = QtWidgets.QPushButton("Not A Drawn Label")
        self.addCleanup(button.deleteLater)
        before = button.maximumWidth()
        with mock.patch.object(debug, "event") as recorded:
            ui_helpers.fit_drawn(button, "D15", "QPushButton",
                                 "Not A Drawn Label")
        self.assertEqual(before, button.maximumWidth(),
                         "a label the document does not draw still pinned "
                         "the widget to something")
        self.assertTrue(recorded.called,
                        "the missing box was not logged - nothing in the "
                        "log would show why the widget kept its own size")


class EveryDrawnNodeIsBoundOrNamed(unittest.TestCase):
    """Every drawn node pins a live widget or is on `DRAWN_EXEMPT` ▸p/one-design-document"""

    def setUp(self):
        amazetheme.forget_drawn_boxes()
        ui_helpers.forget_drawn_nodes_fitted()
        self.addCleanup(amazetheme.forget_drawn_boxes)
        self.addCleanup(ui_helpers.forget_drawn_nodes_fitted)
        build_every_frame(self)
        self.pins = ui_helpers.drawn_nodes_fitted()

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

    def test_the_walk_finds_the_pins(self):
        """A build that pinned nothing would pass by exempting everything ▸p/vacuous-register"""
        self.assertGreaterEqual(
            len(self.pins), 25,    # 28 since Preferences, the largest, is Houdini's QML window
            "the frames built almost no pins, so the completeness check's "
            "empty result proves nothing")
        self.assertEqual(
            {"P01", "P02", "P03a", "P03b", "P04", "P05", "P06", "T01", "T05", "T08", "T20", "T23",
             "T24", "T25", "T26", "L01", "B01", "S01", "G01", "N01", "N01B", "N02"},
            set(amazetheme.DIALOG_LAYOUT)
            - {frame_key for frame_key, _kind, _x, _y in self.pins},
            "the P frames draw Preferences, now Houdini's own QML window, and the panel's areas "
            "are read through their own drawn_* - any other frame listed here "
            "built no widget sized from the document")


class TheCodeDialogMatchesItsDesignFrame(unittest.TestCase):
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

    def test_every_part_is_at_its_drawn_box(self):
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

    def test_the_window_behind_the_form_is_the_drawn_background(self):
        shot = self.dialog.grab().toImage()
        ratio = shot.devicePixelRatio()
        name = self._drawn("QLineEdit")[0]    # beside it, on the Name label's bare left end
        x, y = theme.ui_px(12), name[1] + name[3] // 2
        self.assertEqual(QtGui.QColor(amazetheme.CODE_BACKGROUND).name(),
                         QtGui.QColor(shot.pixel(int(x * ratio), int(y * ratio))).name(),
                         "the window behind the form is not the drawn ground")

    def test_the_current_line_band_is_centred_on_its_letters(self):
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
        background, probe = shot.pixel(shot.width() - 3, shot.height() - 3), shot.width() - 30

        def rows(number, has_text):
            block = editor.document().findBlockByNumber(number)
            top = int(editor.blockBoundingGeometry(block).translated(editor.contentOffset()).top())
            high = int(editor.blockBoundingRect(block).height())
            return top, [y - top for y in range(top, top + high) if has_text(y)]

        _top, descender = rows(0, lambda y: any(shot.pixel(x, y) != background for x in range(2, 40)))
        top, letters = rows(1, lambda y: any(shot.pixel(x, y) not in (background, shot.pixel(probe, y))
                                             for x in range(2, 40)))
        band = [y - top for y in range(shot.height()) if shot.pixel(probe, y) != background]
        self.assertLessEqual(abs((band[0] + band[-1] + 1) - (letters[0] + descender[-1] + 1)) / 2.0,
                             1.0, "the band is not centred on the letters: band %s, cap %d, descender %d"
                             % ((band[0], band[-1]), letters[0], descender[-1]))

    def test_versions_off_hides_the_plus_and_a_disabled_plus_paints_differently(self):
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
    """A rect resized in the regenerated document resizes the real widget once the dialog builds."""

    def setUp(self):
        amazetheme.forget_drawn_boxes()
        self.addCleanup(amazetheme.forget_drawn_boxes)

    def _widened(self, frame_key, kind, at, extra):
        """`DIALOG_LAYOUT` with one rect `extra` wider, in place of an edit in Figma."""
        frame = dict(amazetheme.DIALOG_LAYOUT[frame_key])
        frame["nodes"] = tuple(
            (node[0], node[1], node[2], node[3] + extra, node[4], node[5])
            if (node[0], node[1], node[2]) == (kind,) + at else node
            for node in frame["nodes"])
        return frame

    def test_a_wider_drawn_button_builds_a_wider_button(self):
        from amaze.dialogs import library_dialog
        from amaze.prefs import prefs as prefs_mod
        frame = self._widened("D15", "QPushButton", (237, 193), 5)
        with mock.patch.dict(amazetheme.DIALOG_LAYOUT, {"D15": frame}):
            amazetheme.forget_drawn_boxes()
            dialog = library_dialog.ManageLibrariesDialog(prefs_mod.Prefs())
            self.addCleanup(dialog.deleteLater)
            button = [b for b in dialog.findChildren(QtWidgets.QPushButton)
                      if b.text() == "Remove from List"][0]
            self.assertEqual(
                theme.ui_px(104 + 5), pinned(self, button)[0],
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

class TheFormFamilyMatchesItsFrame(unittest.TestCase):
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

    def test_fields_buttons_and_window_are_where_drawn(self):
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


class TheSaveFamilyHasTheDrawnButtons(unittest.TestCase):
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
                self.assertLess(    # a style may put Cancel first; the drawing does not
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

    def test_a_style_that_lays_Cancel_first_is_reordered_ok_first(self):
        """OK-first systems skip the reorder code; a reversed box tests it ▸p/vacuous-register"""
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
