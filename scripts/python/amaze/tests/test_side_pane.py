"""The pane engine: one pane class, one header, one place and width for the side pane's pages."""

import os
import re
import sys
import types
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze import amazetheme  # noqa: E402
from amaze.core import file_info  # noqa: E402
from amaze.helpers import theme  # noqa: E402
from amaze.panel import info_panel, notes_panel, side_pane  # noqa: E402
from amaze.tests import test_support  # noqa: E402

AMAZE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _sources():
    for folder, _dirs, files in os.walk(AMAZE):
        if os.sep + "tests" in folder:
            continue
        for name in files:
            if name.endswith(".py"):
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as handle:
                    yield os.path.relpath(path, AMAZE), handle.read()


class _Reader(QtCore.QObject):
    ready = QtCore.Signal(str, list)

    def ask(self, key, request):
        pass

    def stop(self):
        pass


class _Pictures(QtCore.QObject):
    ready = QtCore.Signal(str, object)

    def __init__(self, width, height):
        super().__init__()
        self.shape = (width, height)

    def ask(self, path, width):
        image = QtGui.QImage(*self.shape, QtGui.QImage.Format.Format_RGB888)
        image.fill(QtGui.QColor("#804020"))
        self.ready.emit(path, image)

    def stop(self):
        pass


class EveryPartIsBuiltInOnePlace(unittest.TestCase):
    """A second copy of a pane part anywhere in the app fails here."""

    def _only_in(self, pattern, allowed, what):
        found = sorted(path for path, text in _sources() if re.search(pattern, text))
        self.assertEqual(sorted(allowed), found, what)

    def test_only_the_engine_builds_a_pane_header(self):
        self._only_in(r"fill_window\(\s*header\b", ["panel/side_pane.py"],
                      "a pane header is built outside the pane engine")

    def test_only_the_panel_places_panes_and_only_it_and_the_settings_know_their_widths(self):
        self._only_in(r"side_pane\.Pane\(", ["panel/panel.py"], "a pane is placed outside the panel")
        self._only_in(r"notes_panel_width|sidebar_width",
                      ["panel/panel.py", "prefs/persistence.py", "prefs/prefs.py"],
                      "a pane's saved width is handled outside the panel and the settings")

    def test_only_the_engine_builds_two_column_rows_a_picture_and_a_drag_line(self):
        for pattern in (r"class \w+\(.*QTreeWidget\)", r"drawImage\(", r"SplitVCursor"):
            with self.subTest(pattern=pattern):
                found = sorted(path for path, text in _sources() if re.search(pattern, text)
                               and path.startswith("panel" + os.sep))
                self.assertEqual(["panel/side_pane.py"], found)

    def test_every_list_is_a_tree_view_made_by_the_one_function(self):
        views = {path: re.findall(r"class (\w+)\(([^)]*Q(?:Tree|Table|List)(?:View|Widget)\b[^)]*)\)", text)
                 for path, text in _sources()}
        found = sorted((path, name, base.split(".")[-1].split(",")[-1].strip())
                       for path, classes in views.items() for name, base in classes)
        self.assertEqual([
            ("dialogs/library_dialog.py", "DrawnList", "QTreeWidget"),
            ("panel/dragdrop_widgets.py", "DragDropListView", "QListView"),    # the tile grid, not a row list
            ("panel/dragdrop_widgets.py", "DragDropTableView", "QTreeView"),
            ("panel/side_pane.py", "RowsView", "QTreeWidget"),
            ("panel/sidebar.py", "SidebarTreeView", "QTreeView"),
        ], found, "a list was added that is not a tree view, or one of the app's lists changed kind")
        for path, text in _sources():
            names = [name for name, base in views[path] if "Tree" in base]
            if names:
                self.assertIn("ui_helpers.striped_rows(self)", text, "%s builds a list without striped_rows" % path)

    def test_the_pages_are_descriptions(self):
        for module in (notes_panel, info_panel):
            with self.subTest(module=module.__name__):
                self.assertIsInstance(module.DESCRIPTION, side_pane.Page)
        self.assertEqual(("preview", "drag_line", "table"), tuple(part.name for part in info_panel.DESCRIPTION.body))
        self.assertEqual(("text_edit",), tuple(part.name for part in notes_panel.DESCRIPTION.body))


class TheSidePaneKeepsOnePlaceAndWidth(unittest.TestCase):

    def setUp(self):
        self.prefs = types.SimpleNamespace(notes_panel_width=0, save=lambda: None, dir="")
        self.window = QtWidgets.QWidget()
        self.addCleanup(self.window.deleteLater)
        box = QtWidgets.QVBoxLayout(self.window)
        self.splitter = QtWidgets.QSplitter()
        box.addWidget(self.splitter)
        self.splitter.addWidget(QtWidgets.QListView())
        self.pane = side_pane.Pane(self.prefs, "notes_panel_width", 450)
        self.splitter.addWidget(self.pane)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.notes = notes_panel.NotesPanel(self.prefs)
        self.info = info_panel.InfoPanel(self.prefs, _Reader(), pictures=_Pictures(900, 600))
        self.pane.add_page(self.notes)
        self.pane.add_page(self.info)
        self.pane.show_page(self.notes)
        self.window.resize(1500, 700)
        self.window.show()
        _app.processEvents()

    def test_switching_pages_keeps_the_dragged_width_and_moves_nothing(self):
        sizes = self.splitter.sizes()
        self.splitter.setSizes([sizes[0] - 150, sizes[1] + 150])
        _app.processEvents()
        wide = self.pane.width()
        self.assertEqual(sizes[1] + 150, wide)
        resized = []

        class Watch(QtCore.QObject):
            def eventFilter(self, _watched, event):
                if event.type() == QtCore.QEvent.Type.Resize:
                    resized.append(event.size().width())
                return False

        watch = Watch()
        self.pane.installEventFilter(watch)
        for page in (self.info, self.notes, self.info):
            self.pane.show_page(page)
            _app.processEvents()
            self.assertEqual(wide, self.pane.width())
            self.assertEqual(wide, page.width(), "the page is not the pane's width")
            self.assertIs(page, self.pane.page())
        self.assertEqual([], resized, "the pane changed size on a switch")

    def test_one_page_is_shown_and_closing_hides_every_page(self):
        self.pane.show_page(self.info)
        self.assertEqual((True, False), (self.notes.isHidden(), self.info.isHidden()))
        self.pane.show_page(None)
        self.assertTrue(self.pane.isHidden())
        self.assertEqual((True, True), (self.notes.isHidden(), self.info.isHidden()))
        self.assertIsNone(self.pane.page())

    def test_both_headers_are_the_same_build(self):
        def places(page):
            return [(w.x(), w.y(), w.height()) for w in (page._icon_label, page.name_label)]
        for page in (self.notes, self.info):
            self.pane.show_page(page)
            page.set_header("steel", "EXR")
            _app.processEvents()
        self.pane.show_page(self.notes)
        _app.processEvents()
        notes_places = places(self.notes)
        self.pane.show_page(self.info)
        _app.processEvents()
        self.assertEqual(notes_places, places(self.info))
        self.assertEqual(self.notes.header_widget.height(), self.info.header_widget.height())


class NoSizeLoopsTheLayout(unittest.TestCase):
    """Every pane size, pixel by pixel: the layout settles in a few steps. ▸r/info-pane-layout-loop"""

    def test_the_info_page_at_every_height_and_width(self):
        for shape in ((900, 600), (400, 1200), (1600, 300)):
            prefs = types.SimpleNamespace(notes_panel_width=0)
            page = info_panel.InfoPanel(prefs, _Reader(), pictures=_Pictures(*shape))
            self.addCleanup(page.deleteLater)
            page.resize(450, 700)
            page.show()
            rows = tuple(("Row %d" % n, "value") for n in range(7))
            page.set_subject(file_info.Subject("a", "steel", "JPG", rows, (),
                                               file_info.request_for_file("/lib/a.jpg")))
            _app.processEvents()
            steps = [0]

            class Count(QtCore.QObject):
                def eventFilter(self, _watched, event):
                    if event.type() == QtCore.QEvent.Type.Resize:
                        steps[0] += 1
                    return False

            count = Count()
            for part in (page.preview, page.table, page.body_widget):
                part.installEventFilter(count)
            worst = 0
            for width, height in ([(450, h) for h in range(700, 40, -1)] + [(w, 462) for w in range(220, 700)]):
                steps[0] = 0
                page.resize(width, height)
                _app.processEvents()
                worst = max(worst, steps[0])
                tall = page.preview.height() if page.preview.isVisible() else 0
                self.assertLessEqual(tall, page.preview.full_height(page.body_widget.width()),
                                     "the picture area is taller than the picture at full width")
            self.assertLessEqual(worst, 6, "a size took %d resizes of the page's parts to settle" % worst)
            page.hide()


class ThePanelHasTwoPanesBesideTheGrid(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def test_the_splitter_holds_the_categories_pane_the_grid_and_the_side_pane(self):
        panel = self.panel
        splitter = panel.side_pane.parentWidget()
        panes = [splitter.widget(i) for i in range(splitter.count())]
        engine = [pane for pane in panes if isinstance(pane, side_pane.Pane)]
        self.assertEqual([panel.cat_wrapper, panel.side_pane], engine)
        self.assertEqual(3, len(panes), "something else has its own place beside the grid")
        self.assertTrue(panel.cat_wrapper.isAncestorOf(panel.cat_list))
        for page in (panel.notes_panel, panel.info_panel):
            self.assertTrue(panel.side_pane.isAncestorOf(page))

    def test_the_categories_pane_keeps_its_drawn_width_as_its_most(self):
        width = theme.ui_px(self.panel._SIDEBAR["width"])
        self.assertEqual(width, self.panel.cat_wrapper.maximumWidth())


if __name__ == "__main__":
    unittest.main()
