"""The File sidebar as a tree: locations unfold to subfolders read on a worker. ▸r/tree-views"""

import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtTest, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from amaze import amazetheme  # noqa: E402
from amaze.core import category, file_library, locations  # noqa: E402
from amaze.helpers import hostos, theme, ui_helpers  # noqa: E402
from amaze.panel import delegates, sidebar  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401 - arms the sandbox
from amaze.tests.test_file_section import _Prefs, _pump_until  # noqa: E402

COUNT = category.SIDEBAR_COUNT_ROLE


def _tree(testcase, layout) -> str:
    """A fresh folder holding `layout` - None makes a file, a dict a folder; its pointer."""
    root = tempfile.mkdtemp(prefix="amaze_tree_")
    testcase.addCleanup(shutil.rmtree, root, ignore_errors=True)

    def make(base, spec):
        for name, inner in spec.items():
            path = os.path.join(base, name)
            if inner is None:
                open(path, "w").close()
            else:
                os.makedirs(path, exist_ok=True)
                make(path, inner)
    make(root, layout)
    return hostos.canonical_path_key(root).rstrip("/") + "/"


def _model(testcase, *layouts):
    """A File sidebar over one fresh location per layout: (model, prefs, pointers)."""
    roots = [_tree(testcase, layout) for layout in layouts]
    prefs = _Prefs(roots)
    prefs.file_show_unknown = False
    model = file_library.FileFolders(prefs)
    testcase.addCleanup(lambda: _pump_until(lambda: not getattr(model, "_walking", None)))
    return model, prefs, list(model._folders())


def _shown(model, path):
    """What a paint does to a row - ask its count - then wait for the read to land."""
    index = model.index_of(path)
    model.data(index, COUNT)
    landed = _pump_until(lambda: model.data(model.index_of(path), COUNT) is not None)
    if not landed:
        raise AssertionError("the read of %s never landed" % path)
    return model.index_of(path)


def _names(model, index):
    return [model.index(r, 0, index).data() for r in range(model.rowCount(index))]


def _child(pointer, *names) -> str:
    return pointer.rstrip("/") + "/" + "/".join(names)


class ALocationUnfoldsToItsSubfolders(unittest.TestCase):
    """A location's subfolders arrive as its children once its row has been shown."""

    LAYOUT = {"b": {}, "A": {"deep": {}}, "c": {}, ".git": {"x": {}}, "x.png": None}

    def setUp(self):
        self.model, self.prefs, self.roots = _model(self, self.LAYOUT, {"y.png": None})
        self.loc = self.roots[0]

    def test_its_subfolders_arrive_sorted_once_its_row_is_shown(self):
        model = self.model
        first = model.index_of(self.loc)
        self.assertEqual(0, model.rowCount(first), "a row unfolded before its folder was read")
        self.assertFalse(model.hasChildren(first), "an arrow before the folder was read")
        loc = _shown(model, self.loc)
        self.assertTrue(_pump_until(lambda: model.rowCount(model.index_of(self.loc)) == 3),
                        "the subfolders never arrived: %s" % _names(model, loc))
        loc = model.index_of(self.loc)
        self.assertEqual(["A", "b", "c"], _names(model, loc),
                         "not the visible subfolders, sorted as the grid sorts")
        self.assertTrue(model.hasChildren(loc), "a location with subfolders shows no arrow")
        other = _shown(model, self.roots[1])
        self.assertFalse(model.hasChildren(other), "a folder with no subfolders shows an arrow")
        self.assertEqual(0, model.rowCount(other))

    def test_a_subfolder_row_is_no_location_and_browses_itself(self):
        self.prefs.set_file_folder_color(self.loc, "#ff8000")
        model = self.model
        _shown(model, self.loc)
        _pump_until(lambda: model.rowCount(model.index_of(self.loc)) == 3)
        child = model.index_of(_child(self.loc, "A"))
        self.assertTrue(child.isValid(), "the subfolder has no row")
        self.assertIsNone(child.data(model.PathRole),
                          "a subfolder answers as a location, so location verbs reach it")
        self.assertEqual(_child(self.loc, "A"), child.data(model.BrowseRole))
        self.assertEqual("A", child.data())
        self.assertEqual(_child(self.loc, "A"), child.data(QtCore.Qt.ItemDataRole.ToolTipRole))
        self.assertFalse(child.data(category.SIDEBAR_COLOR_ROLE),
                         "a subfolder paints its location's colour bar")
        loc = model.index_of(self.loc)
        self.assertEqual(self.loc, loc.data(model.PathRole))
        self.assertEqual(self.loc, loc.data(model.BrowseRole))
        self.assertIsNone(model.index(0, 0).data(model.BrowseRole), "All browses a folder")

    def test_every_row_finds_its_way_back_up(self):
        model = self.model
        _shown(model, self.loc)
        _pump_until(lambda: model.rowCount(model.index_of(self.loc)) == 3)
        loc = model.index_of(self.loc)
        for row in range(model.rowCount(loc)):
            child = model.index(row, 0, loc)
            self.assertEqual(loc, model.parent(child), "a child names another parent")
            self.assertEqual(child, model.index_of(child.data(model.BrowseRole)))
        self.assertFalse(model.parent(loc).isValid(), "a location has a parent")
        self.assertFalse(model.index_of("/nowhere/at/all").isValid())
        self.assertIsNone(model.parent(), "the QObject parent was lost to the overload")

    def test_qts_model_checker_finds_nothing_through_reads_and_changes(self):
        checker = getattr(QtTest, "QAbstractItemModelTester", None)
        if checker is None:
            self.skipTest("this PySide6 has no QAbstractItemModelTester")
        complaints = []

        def heard(_kind, context, message):
            if context.category == "qt.modeltest" or message.startswith("FAIL"):
                complaints.append(message)
        previous = QtCore.qInstallMessageHandler(heard)
        self.addCleanup(QtCore.qInstallMessageHandler, previous)
        watch = checker(self.model, checker.FailureReportingMode.Warning)
        self.addCleanup(lambda: watch)
        model = self.model
        _shown(model, self.loc)
        _pump_until(lambda: model.rowCount(model.index_of(self.loc)) == 3)
        _shown(model, _child(self.loc, "A"))
        root = self.loc.rstrip("/")
        os.rmdir(os.path.join(root, "b"))
        os.makedirs(os.path.join(root, "d"))
        model.refresh_counts()
        model.data(model.index_of(self.loc), COUNT)
        _pump_until(lambda: _names(model, model.index_of(self.loc)) == ["A", "c", "d"])
        self.assertTrue(model.remove_folder(model.row_of(self.loc)), "premise: refused")
        self.assertTrue(model.add_folder(self.loc), "premise: the add refused")
        _shown(model, self.loc)
        self.assertEqual([], complaints, "Qt's model checker objected")

    def test_a_subfolder_counts_by_its_locations_rule(self):
        model, prefs, roots = _model(self, {"A": {"a.png": None, "b.xyz": None,
                                                  "deeper": {"c.png": None}}})
        loc = roots[0]
        _shown(model, loc)
        _pump_until(lambda: model.rowCount(model.index_of(loc)) == 1)
        child = _shown(model, _child(loc, "A"))
        self.assertEqual(1, child.data(COUNT), "the subfolder counted a kind its location hides")
        prefs.set_file_folder_recursive(loc, True)
        model.refresh_counts()
        model.data(model.index_of(_child(loc, "A")), COUNT)
        self.assertTrue(_pump_until(
            lambda: model.data(model.index_of(_child(loc, "A")), COUNT) == 2),
            "with Subfolder ticked the count stayed flat")

    def test_reading_a_folder_never_happens_on_the_gui_thread(self):
        main = threading.get_ident()
        on_gui = []

        def watched(real):
            def call(path=".", *args, **kwargs):
                if threading.get_ident() == main and any(
                        str(path).startswith(r.rstrip("/")) for r in self.roots):
                    on_gui.append(str(path))
                return real(path, *args, **kwargs)
            return call

        with mock.patch("os.scandir", watched(os.scandir)), \
                mock.patch("os.listdir", watched(os.listdir)):
            _shown(self.model, self.loc)
            _pump_until(lambda: self.model.rowCount(self.model.index_of(self.loc)) == 3)
            _shown(self.model, _child(self.loc, "A"))
        self.assertEqual([], on_gui, "a folder was read on the GUI thread")

    def test_a_refresh_adds_and_drops_only_the_rows_that_changed(self):
        model = self.model
        _shown(model, self.loc)
        _pump_until(lambda: model.rowCount(model.index_of(self.loc)) == 3)
        _shown(model, _child(self.loc, "A"))
        _pump_until(lambda: model.rowCount(model.index_of(_child(self.loc, "A"))) == 1)
        removed, inserted, resets = [], [], []
        model.rowsRemoved.connect(
            lambda p, a, b: removed.append((p.data(model.BrowseRole), a, b)))
        model.rowsInserted.connect(
            lambda p, a, b: inserted.append((p.data(model.BrowseRole), a, b)))
        model.modelReset.connect(lambda: resets.append(1))
        root = self.loc.rstrip("/")
        os.rmdir(os.path.join(root, "b"))
        os.makedirs(os.path.join(root, "d"))
        model.refresh_counts()
        model.data(model.index_of(self.loc), COUNT)
        self.assertTrue(_pump_until(
            lambda: _names(model, model.index_of(self.loc)) == ["A", "c", "d"]),
            "the refresh never landed: %s" % _names(model, model.index_of(self.loc)))
        self.assertEqual([], resets, "a refresh reset the whole sidebar")
        self.assertEqual([(self.loc, 1, 1)], removed, "not just b's row went")
        self.assertEqual([(self.loc, 2, 2)], inserted, "not just d's row came")
        self.assertEqual(1, model.rowCount(model.index_of(_child(self.loc, "A"))),
                         "an unchanged subfolder lost its own children")

    def test_removing_a_location_takes_its_subfolders_with_it(self):
        model = self.model
        _shown(model, self.loc)
        _pump_until(lambda: model.rowCount(model.index_of(self.loc)) == 3)
        sub = _child(self.loc, "A")
        _shown(model, sub)
        self.assertTrue(model.remove_folder(model.row_of(self.loc)), "premise: the remove refused")
        self.assertFalse(model.index_of(sub).isValid(), "a removed location's subfolder kept a row")
        self.assertNotIn(sub, model._counts, "a removed location's subfolder kept its count")

    def test_relocating_a_location_drops_its_old_subfolders(self):
        model = self.model
        _shown(model, self.loc)
        _pump_until(lambda: model.rowCount(model.index_of(self.loc)) == 3)
        moved = _tree(self, {"Z": {}})
        row = model.row_of(self.loc)
        self.assertGreaterEqual(model.relocate_folder(row, moved), 0, "premise: Locate refused")
        new = model.index(row, 0)
        self.assertEqual(0, model.rowCount(new), "the old folder's subfolders stayed")
        pointer = new.data(model.PathRole)
        _shown(model, pointer)
        self.assertTrue(_pump_until(lambda: _names(model, model.index_of(pointer)) == ["Z"]),
                        "the new folder's subfolders never arrived")

    def test_a_read_that_lands_after_its_location_left_adds_nothing(self):
        model = self.model
        main = threading.get_ident()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        real = os.scandir
        held = self.loc.rstrip("/")

        def scanning(path=".", *args, **kwargs):
            if threading.get_ident() != main and str(path).rstrip("/") == held:
                entered.set()
                release.wait(10)
            return real(path, *args, **kwargs)

        with mock.patch("os.scandir", scanning):
            model.data(model.index_of(self.loc), COUNT)
            self.assertTrue(_pump_until(entered.is_set), "the read never ran on a worker")
            self.assertTrue(model.remove_folder(model.row_of(self.loc)), "premise: refused")
            release.set()
            _pump_until(lambda: not model._walking)
        self.assertFalse(model.index_of(_child(self.loc, "A")).isValid(),
                         "a read for a removed location still added its subfolders")


class TheGridBrowsesASubfolderByItsLocationsRules(unittest.TestCase):
    """A subfolder lists what its location's Show ticks show, and follows its Subfolder tick."""

    def setUp(self):
        self.loc = _tree(self, {"A": {"a.png": None, "b.xyz": None,
                                      "deeper": {"c.png": None}}, "top.png": None})
        self.prefs = _Prefs([self.loc])
        self.prefs.file_show_unknown = False
        self.files = file_library.FileFiles(self.prefs)
        self.sub = _child(self.loc, "A")

    def _listed(self):
        return sorted(name for _folder, name in self.files._files)

    def test_a_subfolder_lists_the_kinds_its_location_shows(self):
        self.files.set_folder(self.sub)
        self.assertEqual(["a.png"], self._listed())

    def test_a_subfolder_of_a_recursive_location_lists_what_is_below_it(self):
        self.prefs.set_file_folder_recursive(self.loc, True)
        self.files.set_folder(self.sub)
        self.assertEqual(["a.png", "c.png"], self._listed())

    def test_the_innermost_location_owns_a_folder(self):
        self.assertEqual(self.loc, locations.owner_of(self.prefs, self.sub))
        self.assertEqual(self.loc, locations.owner_of(self.prefs, self.loc))
        self.assertEqual("", locations.owner_of(self.prefs, "/nowhere/at/all"))
        self.prefs.add_file_folder(self.sub + "/")
        inner = locations.owner_of(self.prefs, self.sub + "/deeper")
        self.assertEqual(self.sub, inner.rstrip("/"), "an outer location took a nested one's folder")


STRIPES_BELOW = "QTreeView { paint-alternating-row-colors-for-empty-area: 1; }"    # as Houdini's style


class TheSidebarTreeView(unittest.TestCase):
    """Rows read colour bar, arrow, name; the arrow is the row's own, and Qt's is not drawn."""

    def setUp(self):
        self.model, self.prefs, roots = _model(
            self, {"A": {"deep": {"deeper": {}}}, "B": {}}, {"y.png": None})
        self.loc, self.other = roots
        self.view = self._view(self.model)

    def _view(self, model, kind=None):
        view = (kind or sidebar.SidebarTreeView)()
        self.addCleanup(view.deleteLater)
        self.addCleanup(view.close)
        view.setAlternatingRowColors(True)
        delegate = delegates.SidebarItemDelegate(view)
        delegate.color_role = category.SIDEBAR_COLOR_ROLE
        view.setItemDelegate(delegate)
        view.setModel(model)
        view.resize(220, 300)
        view.show()
        _pump_until(lambda: False, timeout=0.05)
        return view

    def _scanned(self, *paths):
        for path in paths:
            _shown(self.model, path)
            _pump_until(lambda: self.model.hasChildren(self.model.index_of(path)))

    def _rects(self, view, index):
        option = QtWidgets.QStyleOptionViewItem()
        view.initViewItemOption(option)
        option.rect = view.visualRect(index)
        view.itemDelegate().initStyleOption(option, index)
        style = view.style()
        deco = style.subElementRect(QtWidgets.QStyle.SubElement.SE_ItemViewItemDecoration,
                                    option, view)
        text = style.subElementRect(QtWidgets.QStyle.SubElement.SE_ItemViewItemText, option, view)
        return deco, text

    def test_rows_read_bar_then_arrow_then_name(self):
        self._scanned(self.loc)
        bar = delegates.SidebarItemDelegate.BAR
        room = bar + theme.ui_px(amazetheme.SIDEBAR_ARROW_GAP) + theme.ui_px(
            amazetheme.SIDEBAR_ARROW_BOX)
        texts = []
        for path in (self.loc, self.other):
            deco, text = self._rects(self.view, self.model.index_of(path))
            self.assertEqual(room, deco.width(), "%s: not bar, gap and arrow" % path)
            texts.append(text.x())
        self.assertEqual(1, len(set(texts)), "names do not line up: %s" % texts)
        flat = QtGui.QStandardItemModel()
        flat.appendRow(QtGui.QStandardItem("Wood"))
        view = self._view(flat)
        deco, _text = self._rects(view, flat.index(0, 0))
        self.assertEqual(bar, deco.width(), "a flat sidebar grew an arrow's room")

    def test_a_click_on_the_arrow_opens_the_folder_and_selects_nothing(self):
        self._scanned(self.loc)
        view, loc = self.view, self.model.index_of(self.loc)
        clicked = []
        view.clicked.connect(lambda index: clicked.append(index.row()))
        arrow = view.arrow_rect(loc)
        self.assertFalse(arrow.isEmpty(), "a folder with subfolders has no arrow")
        QtTest.QTest.mouseClick(view.viewport(), QtCore.Qt.MouseButton.LeftButton,
                                QtCore.Qt.KeyboardModifier.NoModifier, arrow.center())
        self.assertTrue(view.isExpanded(loc), "the arrow did not open the folder")
        self.assertEqual([], clicked, "the arrow also clicked the row")
        self.assertEqual([], view.selectedIndexes(), "the arrow selected the row")
        QtTest.QTest.mouseClick(view.viewport(), QtCore.Qt.MouseButton.LeftButton,
                                QtCore.Qt.KeyboardModifier.NoModifier, arrow.center())
        self.assertFalse(view.isExpanded(loc), "a second click did not close it")
        rect = view.visualRect(loc)
        name = QtCore.QPoint(rect.right() - rect.width() // 4, rect.center().y())
        QtTest.QTest.mouseClick(view.viewport(), QtCore.Qt.MouseButton.LeftButton,
                                QtCore.Qt.KeyboardModifier.NoModifier, name)
        self.assertEqual([loc.row()], clicked, "a click on the name did not click the row")
        self.assertFalse(view.isExpanded(loc), "a click on the name opened the folder")

    def test_a_double_click_and_the_arrow_keys_open_and_close_a_folder(self):
        self._scanned(self.loc)
        view, loc = self.view, self.model.index_of(self.loc)
        rect = view.visualRect(loc)
        name = QtCore.QPoint(rect.right() - rect.width() // 4, rect.center().y())
        left, none = QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.MouseButton.NoButton
        for kind, buttons in ((QtCore.QEvent.Type.MouseButtonPress, left),    # QTest's dclick
                              (QtCore.QEvent.Type.MouseButtonRelease, none),    # reaches no view
                              (QtCore.QEvent.Type.MouseButtonDblClick, left),    # offscreen
                              (QtCore.QEvent.Type.MouseButtonRelease, none)):
            QtWidgets.QApplication.sendEvent(view.viewport(), QtGui.QMouseEvent(
                kind, QtCore.QPointF(name), QtCore.QPointF(view.viewport().mapToGlobal(name)),
                left, buttons, QtCore.Qt.KeyboardModifier.NoModifier))
        self.assertTrue(view.isExpanded(loc), "a double-click did not open the folder")
        view.setCurrentIndex(loc)
        QtTest.QTest.keyClick(view, QtCore.Qt.Key.Key_Left)
        self.assertFalse(view.isExpanded(loc), "Left did not close the folder")
        QtTest.QTest.keyClick(view, QtCore.Qt.Key.Key_Right)
        self.assertTrue(view.isExpanded(loc), "Right did not open the folder")

    def test_qts_own_arrows_are_not_drawn(self):
        self._scanned(self.loc, _child(self.loc, "A"))
        view, model = self.view, self.model
        view.setAlternatingRowColors(False)    # the indent then shows the same ground as the row's end
        view.expand(model.index_of(self.loc))
        _pump_until(lambda: False, timeout=0.05)
        nested = model.index_of(_child(self.loc, "A"))
        self.assertTrue(model.hasChildren(nested), "premise: the nested folder has subfolders")
        rect = view.visualRect(nested)
        image = view.viewport().grab().toImage()
        ratio = image.devicePixelRatio()
        end = int((rect.right() - 2) * ratio)
        ink = [(x, y) for y in range(int(rect.top() * ratio), int((rect.bottom() + 1) * ratio))
               for x in range(int(rect.x() * ratio))    # the indent, left of the row
               if image.pixelColor(x, y) != image.pixelColor(end, y)]
        self.assertEqual([], ink[:5], "Qt drew an arrow of its own in the indent")

    def test_a_flat_sidebar_paints_as_the_list_did(self):
        flat = QtGui.QStandardItemModel()
        for name in ("All", "Wood", "Metal"):
            flat.appendRow(QtGui.QStandardItem(name))
        views = [self._view(flat, QtWidgets.QListView), self._view(flat)]
        for view in views:    # both stand alike: row 1 current and selected, neither focused
            view.setStyleSheet(STRIPES_BELOW)
            view.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
            view.clearFocus()
            view.selectionModel().setCurrentIndex(
                flat.index(1, 0), QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        _pump_until(lambda: False, timeout=0.05)
        a, b = (view.grab().toImage() for view in views)
        self.assertEqual(a.size(), b.size(), "premise: the two views differ in size")
        rows = sorted({y for y in range(a.height()) for x in range(a.width())
                       if a.pixel(x, y) != b.pixel(x, y)})
        self.assertEqual([], rows[:5], "a flat sidebar does not paint as the list did, below "
                         "the rows or on them (%d pixel rows)" % len(rows))

    def test_what_was_open_reopens_after_a_swap_and_a_reset(self):
        self._scanned(self.loc, _child(self.loc, "A"))
        view, model = self.view, self.model
        view.expand(model.index_of(self.loc))
        view.expand(model.index_of(_child(self.loc, "A")))
        flat = QtGui.QStandardItemModel()
        flat.appendRow(QtGui.QStandardItem("Wood"))
        view.setModel(flat)
        view.setModel(model)
        self.assertTrue(_pump_until(lambda: view.isExpanded(model.index_of(_child(self.loc, "A")))),
                        "a tab switch closed the folders that were open")
        model.switch_model_data()
        for _round in range(3):
            for path in (self.loc, _child(self.loc, "A")):
                if model.index_of(path).isValid():
                    model.data(model.index_of(path), COUNT)
            _pump_until(lambda: view.isExpanded(model.index_of(_child(self.loc, "A"))),
                        timeout=2.0)
        self.assertTrue(view.isExpanded(model.index_of(_child(self.loc, "A"))),
                        "a reset closed the folders that were open")

    def test_reveal_opens_the_way_down_and_stands_on_the_folder(self):
        view, model = self.view, self.model
        deep = _child(self.loc, "A", "deep")
        view.reveal(deep)
        for _round in range(3):    # a paint asks each row it shows; headless, ask as it would
            for path in (self.loc, _child(self.loc, "A")):
                if model.index_of(path).isValid():
                    model.data(model.index_of(path), COUNT)
            _pump_until(lambda: model.index_of(deep).isValid(), timeout=2.0)
        self.assertTrue(_pump_until(lambda: view.currentIndex().data(model.BrowseRole) == deep),
                        "the sidebar never stood on the remembered folder")
        self.assertTrue(view.isExpanded(model.index_of(self.loc)))
        self.assertTrue(view.isExpanded(model.index_of(_child(self.loc, "A"))))


class TheFileTabWalksSubfolders(unittest.TestCase):
    """A subfolder is browsed like a location and never moved, removed or relocated as one."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.folders = self.panel.file_folders_model
        self.loc = self.folders.data(self.folders.index(1, 0), self.folders.PathRole)
        for name in ("a_sub", "b_sub"):
            os.makedirs(os.path.join(self.loc, name), exist_ok=True)
        second = test_support.fresh_files_folder(self)
        self.assertTrue(self.folders.add_folder(second), "premise: a second location")
        self.panel.section_tabs.setChecked("file")
        QtWidgets.QApplication.processEvents()
        _shown(self.folders, self.loc)
        self.assertTrue(_pump_until(
            lambda: self.folders.rowCount(self.folders.index_of(self.loc)) == 3),
            "premise: the fixture location's subfolders never arrived")
        self.sub = self.folders.index_of(_child(self.loc, "b_sub"))    # row 1, a location's row
        self.assertEqual(1, self.sub.row(), "premise: the subfolder is not on row 1")

    def _stand(self, index):
        view = self.panel.cat_list
        view.selectionModel().setCurrentIndex(
            index, QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.panel.update_selected_cat()
        QtWidgets.QApplication.processEvents()

    def test_a_click_on_a_subfolder_browses_it(self):
        self._stand(self.sub)
        files = self.panel.file_files_model
        self.assertEqual(_child(self.loc, "b_sub"), files.browsing())
        self.assertEqual(_child(self.loc, "b_sub"), self.panel.prefs.last_file_folder)

    def test_a_subfolder_is_never_removed_moved_or_relocated_as_a_location(self):
        section = self.panel.sections["file"]
        self.assertFalse(section.sidebar_movable(self.sub), "a subfolder can be dragged")
        before = list(self.folders._folders())
        self._stand(self.sub)
        self.assertEqual([], self.panel.remove_file_folder_user(),
                         "removing with a subfolder selected unregistered a location")
        self.panel._locate_folder_user(self.folders)
        self.assertEqual(before, list(self.folders._folders()),
                         "a subfolder's row reached a location's pointer")
        self.assertEqual(self.folders.index_of(self.loc),
                         sidebar.top_level(self.sub), "a reorder over a subfolder lands elsewhere")

    def test_a_subfolders_menu_greys_the_location_entries(self):
        section = self.panel.sections["file"]
        location = self.folders.index_of(self.loc)
        self.assertTrue(section.on_a_location([location], location), "premise: a location row")
        self.assertFalse(section.on_a_location([self.sub], self.sub),
                         "Locate, Rename, Remove, Show and Label stay live on a subfolder")
        greyed = {entry.label for entry in section.SIDEBAR_MENU
                  if entry.needs == "on_a_location"}
        self.assertEqual({"Locate", "Rename", "Remove", "Show", "Label"}, greyed,
                         "the location entries are not the ones the manual names")

    def test_the_file_tab_reopens_on_a_remembered_subfolder(self):
        sub = _child(self.loc, "b_sub")
        self.panel.section_tabs.setChecked("material")
        self.panel.prefs.last_file_folder = sub
        self.panel.section_tabs.setChecked("file")
        QtWidgets.QApplication.processEvents()
        self.assertEqual(sub, self.panel.file_files_model.browsing(),
                         "the grid shows another folder")
        view, model = self.panel.cat_list, self.folders
        model.data(model.index_of(self.loc), COUNT)
        self.assertTrue(_pump_until(lambda: view.currentIndex().data(model.BrowseRole) == sub),
                        "the sidebar never stood on the remembered subfolder")

    def test_the_live_current_index_keeps_its_parent(self):
        view = self.panel.cat_list
        view.setCurrentIndex(self.sub)
        live = ui_helpers.live_current_index(view)
        self.assertEqual(self.sub, live, "the live index lost the subfolder's parent")


if __name__ == "__main__":
    unittest.main()
