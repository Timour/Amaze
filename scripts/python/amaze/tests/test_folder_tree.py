"""The File sidebar as a tree: locations expand to subfolders read on a worker. ▸r/tree-views"""

import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtTest, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from amaze import amazetheme  # noqa: E402
from amaze.core import category, file_library, folders, locations  # noqa: E402
from amaze.helpers import hostos, theme, ui_helpers  # noqa: E402
from amaze.panel import delegates, sidebar  # noqa: E402
from amaze.tests import test_support  # noqa: E402 - arms the sandbox
from amaze.tests.test_file_section import _Prefs  # noqa: E402

COUNT = category.SIDEBAR_COUNT_ROLE
KNOWN_KINDS = (locations.KIND_IMAGE, locations.KIND_GEO, locations.KIND_HIP)    # Other Files off


def _tree(testcase, layout) -> str:
    """A new folder holding `layout` - None makes a file, a dict a folder; its canonical path."""
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
    prefs.file_show_unknown = False    # Other Files off for a folder outside every location: the scene's
    for root in roots:
        prefs.set_file_folder_kinds(root, KNOWN_KINDS)
    model = file_library.FileFolders(prefs)
    testcase.addCleanup(lambda: test_support.pump_until(lambda: not getattr(model, "_walking", None)))
    return model, prefs, list(model._folders())


def _shown(model, path):
    """Request a row's count as painting does, then wait until the worker's read has finished."""
    index = model.index_of(path)
    model.data(index, COUNT)
    landed = test_support.pump_until(lambda: model.data(model.index_of(path), COUNT) is not None)
    if not landed:
        raise AssertionError("the read of %s never landed" % path)
    return model.index_of(path)


def _names(model, index):
    return [model.index(r, 0, index).data() for r in range(model.rowCount(index))]


def _child(pointer, *names) -> str:
    return pointer.rstrip("/") + "/" + "/".join(names)


class ALocationUnfoldsToItsSubfolders(unittest.TestCase):
    """A location's subfolders are added as its child rows once its row has been shown."""

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
        self.assertTrue(test_support.pump_until(lambda: model.rowCount(model.index_of(self.loc)) == 3),
                        "the subfolder rows were never added: %s" % _names(model, loc))
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
        test_support.pump_until(lambda: model.rowCount(model.index_of(self.loc)) == 3)
        child = model.index_of(_child(self.loc, "A"))
        self.assertTrue(child.isValid(), "the subfolder has no row")
        self.assertIsNone(child.data(model.PathRole),
                          "a subfolder returns a `PathRole`, so location actions apply to it")
        self.assertEqual(_child(self.loc, "A"), child.data(model.BrowseRole))
        self.assertEqual("A", child.data())
        self.assertEqual(_child(self.loc, "A"), child.data(QtCore.Qt.ItemDataRole.ToolTipRole))
        self.assertFalse(child.data(category.SIDEBAR_COLOR_ROLE),
                         "a subfolder paints its location's colour bar")
        loc = model.index_of(self.loc)
        self.assertEqual(self.loc, loc.data(model.PathRole))
        self.assertEqual(self.loc, loc.data(model.BrowseRole))
        self.assertIsNone(model.index(0, 0).data(model.BrowseRole), "the All row has a `BrowseRole`")

    def test_every_row_finds_its_way_back_up(self):
        model = self.model
        _shown(model, self.loc)
        test_support.pump_until(lambda: model.rowCount(model.index_of(self.loc)) == 3)
        loc = model.index_of(self.loc)
        for row in range(model.rowCount(loc)):
            child = model.index(row, 0, loc)
            self.assertEqual(loc, model.parent(child), "a child row returns another parent")
            self.assertEqual(child, model.index_of(child.data(model.BrowseRole)))
        self.assertFalse(model.parent(loc).isValid(), "a location has a parent")
        self.assertFalse(model.index_of("/nowhere/at/all").isValid())
        self.assertIsNone(model.parent(), "`parent()` with no argument no longer returns the QObject parent")

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
        test_support.pump_until(lambda: model.rowCount(model.index_of(self.loc)) == 3)
        _shown(model, _child(self.loc, "A"))
        root = self.loc.rstrip("/")
        os.rmdir(os.path.join(root, "b"))
        os.makedirs(os.path.join(root, "d"))
        model.refresh_counts()
        model.data(model.index_of(self.loc), COUNT)
        test_support.pump_until(lambda: _names(model, model.index_of(self.loc)) == ["A", "c", "d"])
        self.assertTrue(model.remove_folder(model.row_of(self.loc)), "premise: `remove_folder` returned False")
        self.assertTrue(model.add_folder(self.loc), "premise: `add_folder` returned False")
        _shown(model, self.loc)
        hip = _tree(self, {"s1": {}, "s2": {}})
        self.assertTrue(model.set_scene_folder(hip), "premise: the scene folder was not set")
        _shown(model, hip)
        test_support.pump_until(lambda: model.rowCount(model.index_of(hip)) == 2)
        other = _tree(self, {"t": {}})
        self.assertTrue(model.set_scene_folder(other), "premise: the scene folder did not change")
        _shown(model, other)
        test_support.pump_until(lambda: model.rowCount(model.index(1, 0)) == 1)
        self.assertTrue(model.add_folder(other), "premise: no location was added at the scene's folder")
        _shown(model, other)
        same = [model.index(row, 0) for row in range(1, model.rowCount())
                if model.index(row, 0).data(model.BrowseRole) == other]
        self.assertEqual(2, len(same), "the scene row and the location at its folder are not two rows")
        self.assertNotEqual(same[0].internalId(), same[1].internalId(), "the two rows share an internal id")
        for index in same:
            self.assertFalse(model.parent(index).isValid(), "a top row has a parent")
        self.assertTrue(model.set_scene_folder(""), "premise: the scene folder was not cleared")
        _shown(model, other)
        self.assertEqual([], complaints, "QAbstractItemModelTester reported problems")

    def test_a_subfolder_counts_by_its_locations_rule(self):
        model, prefs, roots = _model(self, {"A": {"a.png": None, "b.xyz": None,
                                                  "deeper": {"c.png": None}}})
        loc = roots[0]
        _shown(model, loc)
        test_support.pump_until(lambda: model.rowCount(model.index_of(loc)) == 1)
        child = _shown(model, _child(loc, "A"))
        self.assertEqual(1, child.data(COUNT), "the subfolder counted a kind its location hides")
        prefs.set_file_folder_recursive(loc, True)
        model.refresh_counts()
        model.data(model.index_of(_child(loc, "A")), COUNT)
        self.assertTrue(test_support.pump_until(
            lambda: model.data(model.index_of(_child(loc, "A")), COUNT) == 2),
            "with Subfolder ticked the count left out the nested file")

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
            test_support.pump_until(lambda: self.model.rowCount(self.model.index_of(self.loc)) == 3)
            _shown(self.model, _child(self.loc, "A"))
        self.assertEqual([], on_gui, "a folder was read on the GUI thread")

    def test_a_refresh_adds_and_drops_only_the_rows_that_changed(self):
        model = self.model
        _shown(model, self.loc)
        test_support.pump_until(lambda: model.rowCount(model.index_of(self.loc)) == 3)
        _shown(model, _child(self.loc, "A"))
        test_support.pump_until(lambda: model.rowCount(model.index_of(_child(self.loc, "A"))) == 1)
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
        self.assertTrue(test_support.pump_until(
            lambda: _names(model, model.index_of(self.loc)) == ["A", "c", "d"]),
            "the refresh never updated the rows: %s" % _names(model, model.index_of(self.loc)))
        self.assertEqual([], resets, "a refresh reset the whole sidebar")
        self.assertEqual([(self.loc, 1, 1)], removed, "the removed rows are not just b's row")
        self.assertEqual([(self.loc, 2, 2)], inserted, "the inserted rows are not just d's row")
        self.assertEqual(1, model.rowCount(model.index_of(_child(self.loc, "A"))),
                         "an unchanged subfolder lost its own children")

    def test_a_refresh_asks_the_views_to_read_every_known_count_again(self):
        model = self.model
        _shown(model, self.loc)
        test_support.pump_until(lambda: model.rowCount(model.index_of(self.loc)) == 3)
        changed = []
        model.dataChanged.connect(lambda a, b, roles=(): changed.append(
            (a.parent().data(model.BrowseRole), a.row(), b.row(), list(roles))))
        model.refresh_counts()
        self.assertIn((None, 0, model.rowCount() - 1, [COUNT]), changed,
                      "a refresh emitted no dataChanged, so the top counts stay stale until a repaint")
        self.assertIn((self.loc, 0, 2, [COUNT]), changed,
                      "a refresh did not emit one dataChanged range for the subfolder counts")
        self.assertEqual(2, len(changed), "a refresh emitted one dataChanged per row")
        self.assertIsNotNone(model.data(model.index_of(self.loc), COUNT),
                             "a refresh cleared the old count before the new one was read")

    def test_rows_that_come_or_go_side_by_side_are_one_signal(self):
        model, _prefs, (loc,) = _model(self, {"A": {"p": {}, "q": {}, "r": {}, "s": {}}})
        _shown(model, loc)
        test_support.pump_until(lambda: model.rowCount(model.index_of(loc)) == 1)
        inside = _child(loc, "A")
        self.assertEqual(0, model.rowCount(model.index_of(inside)))    # read before its scan, as painting does
        removed, inserted = [], []
        model.rowsRemoved.connect(
            lambda p, a, b: removed.append((p.data(model.BrowseRole), a, b)))
        model.rowsInserted.connect(
            lambda p, a, b: inserted.append((p.data(model.BrowseRole), a, b)))
        _shown(model, inside)
        self.assertTrue(test_support.pump_until(lambda: model.rowCount(model.index_of(inside)) == 4))
        self.assertEqual([(inside, 0, 3)], inserted, "four subfolders of one read were four signals")
        for name in ("q", "r"):
            os.rmdir(os.path.join(inside, name))
        model.refresh_counts()
        model.data(model.index_of(inside), COUNT)
        self.assertTrue(test_support.pump_until(
            lambda: _names(model, model.index_of(inside)) == ["p", "s"]))
        self.assertEqual([(inside, 1, 2)], removed, "two adjacent rows were removed with two signals")

    def test_names_that_differ_only_by_case_keep_one_order(self):
        self.assertEqual(["A", "a", "b"], folders.name_order(["b", "a", "A"]))
        self.assertEqual(["A", "a", "b"], folders.name_order(["a", "b", "A"]),
                         "the order followed the disk's, so a refresh could show a row twice")

    def test_the_rows_are_asked_without_a_missing_attribute(self):
        self.assertTrue("_held" in vars(self.model),    # ▸r/qobject-missing-attribute
                        "`_held` is not set, so every row lookup pays Qt's cost for a missing attribute")

    def test_no_more_than_two_folders_are_read_at_once(self):
        self.assertLessEqual(self.model.COUNT_WORKERS, 2,    # ▸r/count-workers
                             "four counters at once doubled the sidebar's paint time on a large tree")

    def test_removing_a_location_takes_its_subfolders_with_it(self):
        model = self.model
        _shown(model, self.loc)
        test_support.pump_until(lambda: model.rowCount(model.index_of(self.loc)) == 3)
        sub = _child(self.loc, "A")
        _shown(model, sub)
        self.assertTrue(model.remove_folder(model.row_of(self.loc)), "premise: `remove_folder` returned False")
        self.assertFalse(model.index_of(sub).isValid(), "a removed location's subfolder kept a row")
        self.assertNotIn(sub, model._counts, "a removed location's subfolder kept its count")

    def test_relocating_a_location_drops_its_old_subfolders(self):
        model = self.model
        _shown(model, self.loc)
        test_support.pump_until(lambda: model.rowCount(model.index_of(self.loc)) == 3)
        moved = _tree(self, {"Z": {}})
        row = model.row_of(self.loc)
        self.assertGreaterEqual(model.relocate_folder(row, moved), 0, "premise: `relocate_folder` failed")
        new = model.index(row, 0)
        self.assertEqual(0, model.rowCount(new), "the old folder's subfolders stayed")
        pointer = new.data(model.PathRole)
        _shown(model, pointer)
        self.assertTrue(test_support.pump_until(lambda: _names(model, model.index_of(pointer)) == ["Z"]),
                        "the new folder's subfolder rows were never added")

    def test_locate_onto_another_registered_location_is_refused(self):
        model = self.model
        other = self.roots[1]
        _shown(model, other)
        before = list(model._folders())
        removed = []
        model.rowsRemoved.connect(lambda p, a, b: removed.append((a, b)))
        spelled = other.rstrip("/")    # the picker returns no trailing separator
        self.assertEqual(folders.ALREADY_A_LOCATION, model.relocate_folder(model.row_of(self.loc), spelled),
                         "Locate onto a folder already registered was not refused")
        self.assertEqual(before, list(model._folders()), "a refused Locate changed the locations")
        self.assertEqual(len(before), len(locations.registered_paths(self.prefs)),
                         "a refused Locate dropped a registered location")
        self.assertEqual([], removed, "a refused Locate removed rows")

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
            self.assertTrue(test_support.pump_until(entered.is_set), "the read never ran on a worker")
            self.assertTrue(model.remove_folder(model.row_of(self.loc)), "premise: not removed")
            release.set()
            test_support.pump_until(lambda: not model._walking)
        self.assertFalse(model.index_of(_child(self.loc, "A")).isValid(),
                         "a read for a removed location still added its subfolders")


class TheSceneFolderIsOneMoreTopRow(unittest.TestCase):
    """The scene folder is a fixed row above the locations, read by the same `FileFolders` code."""

    def setUp(self):
        self.model, self.prefs, self.roots = _model(self, {"x.png": None}, {"y.png": None})
        self.hip = _tree(self, {"one": {"deep": {}}, "two": {}, "a.png": None, "b.png": None,
                                "c.xyz": None})

    def _set(self, path=None):
        self.assertTrue(self.model.set_scene_folder(self.hip if path is None else path),
                        "premise: the scene folder did not change")

    def test_it_sits_under_all_before_every_location(self):
        model = self.model
        self._set()
        self.assertEqual(len(self.roots) + 2, model.rowCount())
        row = model.index(1, 0)
        self.assertEqual(model.SCENE_LABEL, row.data())
        self.assertEqual(self.hip, row.data(QtCore.Qt.ItemDataRole.ToolTipRole))
        self.assertIsNone(row.data(model.PathRole), "the scene row returns a `PathRole`")
        self.assertEqual(self.hip, row.data(model.BrowseRole))
        self.assertEqual("", row.data(category.SIDEBAR_COLOR_ROLE))
        self.assertTrue(model.is_scene_row(row))
        self.assertEqual(1, model.scene_row())
        self.assertEqual(self.hip, model.scene_folder())
        for n, root in enumerate(self.roots):
            self.assertEqual(n + 2, model.row_of(root), "a location did not move down one row")
            self.assertEqual(root, model.index(n + 2, 0).data(model.PathRole))
            self.assertFalse(model.is_scene_row(model.index(n + 2, 0)))
        self.assertFalse(model.is_scene_row(model.index(0, 0)), "`is_scene_row` is true for the All row")
        self.assertEqual(1, model.row_of(self.hip))
        self.assertEqual(row, model.index_of(self.hip))

    def test_it_counts_and_unfolds_like_a_location_and_all_leaves_it_out(self):
        model = self.model
        self._set()
        row = _shown(model, self.hip)
        self.assertEqual(2, row.data(COUNT), "the scene row counted by another rule")
        self.assertTrue(test_support.pump_until(lambda: model.rowCount(model.index(1, 0)) == 2),
                        "the scene folder's subfolder rows were never added")
        self.assertEqual(["one", "two"], _names(model, model.index(1, 0)))
        sub = model.index_of(_child(self.hip, "one"))
        self.assertTrue(sub.isValid(), "index_of does not find a subfolder of the scene folder")
        self.assertEqual(model.index(1, 0), model.parent(sub))
        self.assertIsNone(sub.data(model.PathRole))
        for root in self.roots:
            _shown(model, root)
        self.assertTrue(test_support.pump_until(lambda: model.index(0, 0).data(COUNT) is not None))
        self.assertEqual(2, model.index(0, 0).data(COUNT), "All counted the scene folder")

    def test_rows_are_found_through_the_tops_and_rules_through_the_locations(self):
        model = self.model
        self._set()
        sub = _child(self.hip, "one", "deep")
        self.assertEqual(self.hip, model.top_of(sub), "`top_of` found no top row for a scene subfolder")
        self.assertEqual(sub, model.location_of(sub), "`location_of` gave a scene subfolder a location")
        self.assertEqual(self.roots[0], model.top_of(_child(self.roots[0], "x")))
        self.assertEqual("/nowhere/at/all", model.top_of("/nowhere/at/all"))
        inner = _child(self.roots[0], "shot") + "/"
        os.makedirs(inner)
        self._set(inner)
        self.assertEqual(self.roots[0], model.location_of(inner),
                         "`location_of` did not return the location holding the scene folder")
        self.assertEqual(inner, model.top_of(_child(inner, "x")))

    def test_a_scene_change_repoints_the_row_in_place(self):
        model = self.model
        self._set()
        _shown(model, self.hip)
        self.assertTrue(test_support.pump_until(lambda: model.rowCount(model.index(1, 0)) == 2))
        held = QtCore.QPersistentModelIndex(model.index(1, 0))
        moved, removed = [], []
        model.scene_folder_changed.connect(lambda old, new: moved.append((old, new)))
        model.rowsRemoved.connect(lambda p, a, b: removed.append((p.data(model.BrowseRole), a, b)))
        other = _tree(self, {"z": {}})
        self.assertTrue(model.set_scene_folder(other.rstrip("/")))
        self.assertEqual([(self.hip, other)], moved, "`scene_folder_changed` was not emitted once")
        self.assertEqual([(self.hip, 0, 1)], removed, "the old subfolder rows were not removed")
        self.assertEqual(1, held.row(), "a persistent index no longer points at the scene row")
        self.assertEqual(other, held.data(model.BrowseRole))
        self.assertEqual(0, model.rowCount(model.index(1, 0)), "the old subfolders stayed")
        _shown(model, other)
        self.assertTrue(test_support.pump_until(lambda: _names(model, model.index(1, 0)) == ["z"]),
                        "the new folder's subfolder rows were never added")
        self.assertFalse(model.set_scene_folder(other), "setting the same folder returned True")
        self.assertEqual(1, len(moved))
        self.assertTrue(model.set_scene_folder(""))
        self.assertIsNone(model.scene_row())
        self.assertEqual(len(self.roots) + 1, model.rowCount())
        self.assertEqual(self.roots[0], model.index(1, 0).data(model.PathRole),
                         "the locations did not move up one row")
        self.assertEqual(1, len(moved), "clearing emitted `scene_folder_changed`")

    def test_no_scene_folder_no_fixed_row(self):
        model = self.model
        self.assertIsNone(model.scene_row())
        self.assertEqual("", model.scene_folder())
        self.assertEqual(self.roots[0], model.registered_at(1))
        self.assertFalse(model.set_scene_folder(""))

    def test_no_location_verb_reaches_the_scene_row(self):
        model = self.model
        self._set()
        before = list(model._folders())
        self.assertEqual("", model.registered_at(1))
        self.assertEqual("", model.registered_at(0))
        self.assertEqual(self.roots[0], model.registered_at(2))
        self.assertEqual("", model.registered_at(len(self.roots) + 2))
        self.assertFalse(model.remove_folder(1), "the scene row was removed")
        self.assertFalse(model.unregister_folder(1), "the scene row was removed")
        self.assertEqual(-1, model.relocate_folder(1, self.roots[1]), "the scene row relocated")
        self.assertFalse(model.move_folder(1, 2), "the scene row moved")
        self.assertFalse(model.move_folder(2, 1), "a location moved above the scene row")
        self.assertEqual(before, list(model._folders()), "a location path changed")
        self.assertEqual(self.hip, model.scene_folder())


class TheGridBrowsesASubfolderByItsLocationsRules(unittest.TestCase):
    """A subfolder lists what its location's Show ticks show, and follows its Subfolder tick."""

    def setUp(self):
        self.loc = _tree(self, {"A": {"a.png": None, "b.xyz": None,
                                      "deeper": {"c.png": None}}, "top.png": None})
        self.prefs = _Prefs([self.loc])
        self.prefs.set_file_folder_kinds(self.loc, KNOWN_KINDS)
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
        self.assertEqual(self.sub, inner.rstrip("/"), "`owner_of` chose the outer location over a nested one")


STRIPES_BELOW = "QTreeView { paint-alternating-row-colors-for-empty-area: 1; }"    # as Houdini's style


class TheSidebarTreeView(unittest.TestCase):
    """Rows show colour bar, arrow, name; the delegate draws the arrow, and Qt's is not drawn."""

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
        test_support.pump_until(lambda: False, timeout=0.05)
        return view

    def _scanned(self, *paths):
        for path in paths:
            _shown(self.model, path)
            test_support.pump_until(lambda: self.model.hasChildren(self.model.index_of(path)))

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
        self.assertEqual(bar, deco.width(), "a flat sidebar reserved space for an arrow")

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
        self.assertEqual([], clicked, "a click on the arrow also emitted `clicked`")
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
        view.setAlternatingRowColors(False)    # the indent then has the same background as the row's end
        view.expand(model.index_of(self.loc))
        test_support.pump_until(lambda: False, timeout=0.05)
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
        for view in views:    # same state in both: row 1 current and selected, neither focused
            view.setStyleSheet(STRIPES_BELOW)
            view.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
            view.clearFocus()
            view.selectionModel().setCurrentIndex(
                flat.index(1, 0), QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        test_support.pump_until(lambda: False, timeout=0.05)
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
        self.assertTrue(test_support.pump_until(lambda: view.isExpanded(model.index_of(_child(self.loc, "A")))),
                        "a tab switch closed the folders that were open")
        model.switch_model_data()
        for _round in range(3):
            for path in (self.loc, _child(self.loc, "A")):
                if model.index_of(path).isValid():
                    model.data(model.index_of(path), COUNT)
            test_support.pump_until(lambda: view.isExpanded(model.index_of(_child(self.loc, "A"))),
                        timeout=2.0)
        self.assertTrue(view.isExpanded(model.index_of(_child(self.loc, "A"))),
                        "a reset closed the folders that were open")

    def test_reveal_opens_the_way_down_and_stands_on_the_folder(self):
        view, model = self.view, self.model
        deep = _child(self.loc, "A", "deep")
        view.reveal(deep)
        for _round in range(3):    # painting requests each visible row's count; offscreen, request them here
            for path in (self.loc, _child(self.loc, "A")):
                if model.index_of(path).isValid():
                    model.data(model.index_of(path), COUNT)
            test_support.pump_until(lambda: model.index_of(deep).isValid(), timeout=2.0)
        self.assertTrue(test_support.pump_until(lambda: view.currentIndex().data(model.BrowseRole) == deep),
                        "the sidebar never made the remembered folder current")
        self.assertTrue(view.isExpanded(model.index_of(self.loc)))
        self.assertTrue(view.isExpanded(model.index_of(_child(self.loc, "A"))))

    def test_a_click_before_the_read_lands_keeps_the_row_clicked(self):
        """A remembered folder still expanding never takes the selection from a row the user clicked."""
        view, model = self.view, self.model
        deep = _child(self.loc, "A", "deep")
        view.reveal(deep)
        other = view.visualRect(model.index_of(self.other)).center()
        QtTest.QTest.mouseClick(view.viewport(), QtCore.Qt.MouseButton.LeftButton,
                                QtCore.Qt.KeyboardModifier.NoModifier, other)
        self.assertEqual(self.other, view.currentIndex().data(model.BrowseRole),
                         "premise: the click did not make the other location current")
        for _round in range(3):
            for path in (self.loc, _child(self.loc, "A")):
                if model.index_of(path).isValid():
                    model.data(model.index_of(path), COUNT)
            test_support.pump_until(lambda: model.index_of(deep).isValid(), timeout=2.0)
        self.assertTrue(model.index_of(deep).isValid(), "premise: the read never finished")
        test_support.pump_until(lambda: False, timeout=0.05)
        self.assertEqual([self.other], [i.data(model.BrowseRole) for i in view.selectedIndexes()],
                         "the remembered folder replaced the clicked row's selection")
        self.assertEqual(self.other, view.currentIndex().data(model.BrowseRole))


class TheFileTabWalksSubfolders(unittest.TestCase):
    """A subfolder is browsed like a location and never moved, removed or relocated as one."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.folders = self.panel.file_folders_model
        self.loc = self.folders.registered_at(self.folders._offset())
        for name in ("a_sub", "b_sub", "c_sub"):
            os.makedirs(os.path.join(self.loc, name), exist_ok=True)
        second = test_support.fresh_files_folder(self)
        self.assertTrue(self.folders.add_folder(second), "premise: the second location was not added")
        self.panel.section_tabs.setChecked("file")
        QtWidgets.QApplication.processEvents()
        _shown(self.folders, self.loc)
        self.assertTrue(test_support.pump_until(
            lambda: self.folders.rowCount(self.folders.index_of(self.loc)) == 4),
            "premise: the fixture location's subfolder rows were never added")
        self.sub = self.folders.index_of(_child(self.loc, "c_sub"))    # the first location's row number
        self.assertEqual(self.folders._offset(), self.sub.row(),
                         "premise: the subfolder is not on the first location's row")

    def _stand(self, index):
        view = self.panel.cat_list
        view.selectionModel().setCurrentIndex(
            index, QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.panel.update_selected_cat()
        QtWidgets.QApplication.processEvents()

    def test_a_click_on_a_subfolder_browses_it(self):
        self._stand(self.sub)
        files = self.panel.file_files_model
        self.assertEqual(_child(self.loc, "c_sub"), files.browsing())
        self.assertEqual(_child(self.loc, "c_sub"), self.panel.prefs.last_file_folder)

    def test_a_subfolder_is_never_removed_moved_or_relocated_as_a_location(self):
        section = self.panel.sections["file"]
        self.assertFalse(section.sidebar_movable(self.sub), "a subfolder can be dragged")
        before = list(self.folders._folders())
        self._stand(self.sub)
        self.assertEqual([], self.panel.remove_file_folder_user(),
                         "removing with a subfolder selected unregistered a location")
        self.panel.locate_folder_user(self.folders)
        self.assertEqual(before, list(self.folders._folders()),
                         "Locate on a subfolder's row changed a location's path")
        self.assertEqual(self.folders.index_of(self.loc),
                         sidebar.top_level(self.sub), "`top_level` of a subfolder is not its location's row")

    def test_locate_and_add_on_a_folder_already_a_location_say_so(self):
        import hou
        from amaze import messages
        second = self.folders._folders()[1].rstrip("/")    # the picker returns no trailing separator
        before = list(self.folders._folders())
        self._stand(self.folders.index_of(self.loc))
        ui = mock.Mock()
        ui.selectFile.return_value = second
        with mock.patch.object(hou, "ui", ui, create=True):
            self.panel.locate_folder_user(self.folders)
            self.assertEqual(messages.LOCATION_ALREADY_ADDED, ui.displayMessage.call_args[0][0],
                             "a Locate onto a location showed a message other than `LOCATION_ALREADY_ADDED`")
            ui.displayMessage.reset_mock()
            self.panel.add_file_folder_user()
            self.assertTrue(ui.displayMessage.called, "adding a location twice showed no message")
            self.assertEqual(messages.LOCATION_ALREADY_ADDED, ui.displayMessage.call_args[0][0])
        self.assertEqual(before, list(self.folders._folders()))

    def test_a_subfolders_menu_greys_the_location_entries(self):
        section = self.panel.sections["file"]
        location = self.folders.index_of(self.loc)
        self.assertTrue(section.on_a_location([location], location), "premise: a location row")
        self.assertFalse(section.on_a_location([self.sub], self.sub),
                         "Locate, Rename, Remove, Show and Label stay enabled on a subfolder")
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
        self.assertTrue(test_support.pump_until(lambda: view.currentIndex().data(model.BrowseRole) == sub),
                        "the sidebar never made the remembered subfolder current")

    def test_the_live_current_index_keeps_its_parent(self):
        view = self.panel.cat_list
        view.setCurrentIndex(self.sub)
        live = ui_helpers.live_current_index(view)
        self.assertEqual(self.sub, live, "the live index lost the subfolder's parent")


class EveryModelThatUnfoldsSaysWhatARowBrowses(unittest.TestCase):
    """The sidebar keeps a model's open rows by `BrowseRole` once `unfolds` is true."""

    def test_every_model_declaring_unfolds_has_a_browse_role(self):
        """Found by parsing the package source, so a new model with `unfolds` is covered too."""
        import ast
        import importlib
        package = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        defined = []
        for root, dirs, files in os.walk(package):
            dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__")]
            for name in sorted(n for n in files if n.endswith(".py")):
                path = os.path.join(root, name)
                module = ".".join(["amaze"] + os.path.relpath(path, package)[:-3].split(os.sep))
                with open(path, encoding="utf-8") as handle:
                    tree = ast.parse(handle.read())
                for node in tree.body:
                    if not isinstance(node, ast.ClassDef):
                        continue
                    targets = [t for item in node.body
                               for t in (item.targets if isinstance(item, ast.Assign) else
                                         [item.target] if isinstance(item, ast.AnnAssign) else [])]
                    defined.append((
                        module[:-len(".__init__")] if module.endswith(".__init__") else module,
                        node.name,
                        {b.attr if isinstance(b, ast.Attribute) else getattr(b, "id", "")
                         for b in node.bases},
                        any(isinstance(t, ast.Name) and t.id == "unfolds" for t in targets)))
        family = {name for _module, name, _bases, declares in defined if declares}
        grew = True
        while grew:
            grew = False
            for _module, name, bases, _declares in defined:
                if name not in family and bases & family:
                    family.add(name)
                    grew = True
        unfolding = [cls for cls in (getattr(importlib.import_module(module), name)
                                     for module, name, _bases, _declares in defined
                                     if name in family)
                     if getattr(cls, "unfolds", False)]
        self.assertTrue(unfolding, "premise: no model in the package unfolds, so this checks nothing")
        for cls in unfolding:
            self.assertTrue(
                hasattr(cls, "BrowseRole"),
                "%s unfolds but declares no BrowseRole, which the sidebar reads for "
                "every row it opens" % cls.__name__)


if __name__ == "__main__":
    unittest.main()
