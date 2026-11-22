"""The File sidebar as a tree: locations expand to subfolders read on a worker. ▸r/tree-views"""

import contextlib
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
from amaze.core import category, file_library, folders, grid_columns, locations, sidebar_model  # noqa: E402
from amaze.helpers import hostos, theme  # noqa: E402
from amaze.panel import delegates, sidebar  # noqa: E402
from amaze.tests import test_support  # noqa: E402 - arms the sandbox
from amaze.tests.test_file_section import _Prefs  # noqa: E402

COUNT = category.SIDEBAR_COUNT_ROLE


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


def _checker_complaints(testcase, *models) -> list:
    """What Qt's model checker reports on each model while the test runs. ▸r/tree-views"""
    checker = getattr(QtTest, "QAbstractItemModelTester", None)
    if checker is None:
        testcase.skipTest("this PySide6 has no QAbstractItemModelTester")
    complaints = []

    def record_failure(_kind, context, message):
        if context.category == "qt.modeltest" or message.startswith("FAIL"):
            complaints.append(message)
    previous = QtCore.qInstallMessageHandler(record_failure)
    testcase.addCleanup(QtCore.qInstallMessageHandler, previous)
    watches = [checker(model, checker.FailureReportingMode.Warning) for model in models]
    testcase.addCleanup(lambda: watches)
    return complaints


class ALocationUnfoldsToItsSubfolders(unittest.TestCase):
    """A location's subfolders are added as its child rows once its row has been shown."""

    LAYOUT = {"b": {}, "A": {"deep": {}}, "c": {}, ".git": {"x": {}}, "x.png": None}

    def setUp(self):
        self.model, self.prefs, self.roots = _model(self, self.LAYOUT, {"y.png": None})
        self.loc = self.roots[0]

    def test_its_subfolders_are_added_sorted_once_its_row_is_shown(self):
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

    def test_every_child_row_returns_its_location_as_parent(self):
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

        def record_failure(_kind, context, message):
            if context.category == "qt.modeltest" or message.startswith("FAIL"):
                complaints.append(message)
        previous = QtCore.qInstallMessageHandler(record_failure)
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

    def test_a_subfolder_counts_the_files_in_its_own_folder(self):
        model, prefs, roots = _model(self, {"A": {"a.png": None, "b.xyz": None,
                                                  "deeper": {"c.png": None}}})
        loc = roots[0]
        _shown(model, loc)
        test_support.pump_until(lambda: model.rowCount(model.index_of(loc)) == 1)
        child = _shown(model, _child(loc, "A"))
        self.assertEqual(2, child.data(COUNT),
                         "the subfolder did not count its two files, or counted the one below it")

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

    def test_a_refresh_adds_and_removes_only_the_rows_that_changed(self):
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

    def test_adjacent_rows_added_or_removed_together_emit_one_signal(self):
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

    def test_removing_a_location_removes_its_subfolders(self):
        model = self.model
        _shown(model, self.loc)
        test_support.pump_until(lambda: model.rowCount(model.index_of(self.loc)) == 3)
        sub = _child(self.loc, "A")
        _shown(model, sub)
        self.assertTrue(model.remove_folder(model.row_of(self.loc)), "premise: `remove_folder` returned False")
        self.assertFalse(model.index_of(sub).isValid(), "a removed location's subfolder kept a row")
        self.assertNotIn(sub, model._counts, "a removed location's subfolder kept its count")

    def test_relocating_a_location_removes_its_old_subfolders(self):
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

    def test_locate_onto_another_location_returns_already_a_location(self):
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

    def test_a_read_finishing_after_its_location_was_removed_adds_nothing(self):
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

    def test_it_is_listed_under_all_before_every_location(self):
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
        self.assertEqual(3, row.data(COUNT), "the scene row did not count every file in its folder")
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

    def test_no_location_action_changes_the_scene_row(self):
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


class TheGridBrowsesASubfolder(unittest.TestCase):
    """A subfolder lists every file in its own folder, and none of the folders below it."""

    def setUp(self):
        self.loc = _tree(self, {"A": {"a.png": None, "b.xyz": None,
                                      "deeper": {"c.png": None}}, "top.png": None})
        self.prefs = _Prefs([self.loc])
        self.files = file_library.FileFiles(self.prefs)
        self.sub = _child(self.loc, "A")

    def _listed(self):
        return sorted(name for _folder, name in self.files._files)

    def test_a_subfolder_lists_its_own_files_of_every_kind(self):
        self.files.set_folder(self.sub)
        self.assertEqual(["a.png", "b.xyz"], self._listed())

    def test_owner_of_returns_the_innermost_location(self):
        self.assertEqual(self.loc, locations.owner_of(self.prefs, self.sub))
        self.assertEqual(self.loc, locations.owner_of(self.prefs, self.loc))
        self.assertEqual("", locations.owner_of(self.prefs, "/nowhere/at/all"))
        self.prefs.add_file_folder(self.sub + "/")
        inner = locations.owner_of(self.prefs, self.sub + "/deeper")
        self.assertEqual(self.sub, inner.rstrip("/"), "`owner_of` chose the outer location over a nested one")


EMPTY_AREA_ROW_COLORS ="QTreeView { paint-alternating-row-colors-for-empty-area: 1; }"    # as Houdini's style
NO_EMPTY_AREA_ROW_COLORS = "QTreeView { paint-alternating-row-colors-for-empty-area: 0; }"


class _NestedCategories(QtGui.QStandardItemModel):
    """A sidebar model with rows under a row, as a section other than File could have."""

    unfolds = True
    BrowseRole = QtCore.Qt.ItemDataRole.UserRole + 40


class _NestedCategoryList(category.Categories):
    """A category list where Wood has Oak under it, as sub-categories would give."""

    unfolds = True

    def child_keys(self, key) -> list:
        return ["Oak"] if key == "Wood" else []

    def key_above(self, key) -> str:
        return "Wood" if key == "Oak" else ""


class _OnlineCategories(QtCore.QObject):
    """What MatxSidebarModel reads of the online library: its categories and its reset."""

    modelReset = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.names = []

    def categories(self) -> list:
        return list(self.names)


class TheSidebarTreeView(unittest.TestCase):
    """Rows are a colour cell, then the name with the style's own arrow; none of it the app's code."""

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
        view.setItemDelegate(delegates.SidebarItemDelegate(view))
        view.setModel(model)
        view.resize(220, 300)
        view.show()
        test_support.pump_until(lambda: False, timeout=0.05)
        return view

    def _styled_as_houdini(self, view):
        """Puts the view in a parent whose sheet asks for row colours below the last row."""
        host = QtWidgets.QWidget()
        self.addCleanup(host.deleteLater)
        self.addCleanup(host.close)
        host.setStyleSheet(EMPTY_AREA_ROW_COLORS)
        host.resize(view.size())
        view.setParent(host)
        view.move(0, 0)
        host.show()
        view.show()
        test_support.pump_until(lambda: False, timeout=0.05)
        return view

    @staticmethod
    def _rows_end(view) -> int:
        """The viewport y where the last row ends."""
        model = view.model()
        return view.visualRect(model.index(model.rowCount() - 1, 0)).bottom() + 1

    @staticmethod
    def _column(view) -> tuple:
        """(the pixels of the viewport's middle column, top to bottom; the image's pixel ratio)."""
        image = view.viewport().grab().toImage()
        return ([image.pixel(image.width() // 2, y) for y in range(image.height())],
                image.devicePixelRatio())

    @staticmethod
    def _below(column, top) -> list:
        """A column's pixels from viewport y `top` down."""
        pixels, ratio = column
        return pixels[int((top + 2) * ratio):]

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

    def _press_bands(self, view, index, step=2):
        """What a left click does at every `step` px across `index`'s row: [(first x, last x, what)]."""
        chosen = []
        view.row_chosen.connect(lambda i: chosen.append(i))
        self.addCleanup(view.row_chosen.disconnect)
        persistent, bands = QtCore.QPersistentModelIndex(index), []
        for x in range(1, view.viewport().width() - 1, step):
            view.expandAll()
            view.highlight(view.model().index(0, 0))
            test_support.pump_until(lambda: False, timeout=0.001)
            index = QtCore.QModelIndex(persistent)
            was_open, y = view.isExpanded(index), view.visualRect(index).center().y()
            del chosen[:]
            QtTest.QTest.mouseClick(view.viewport(), QtCore.Qt.MouseButton.LeftButton,
                                    QtCore.Qt.KeyboardModifier.NoModifier, QtCore.QPoint(x, y))
            toggled = view.isExpanded(QtCore.QModelIndex(persistent)) != was_open
            what = ("toggles" if toggled else "") + (" chooses" if chosen else "")
            what = what.strip() or "nothing"
            if bands and bands[-1][2] == what:
                bands[-1] = (bands[-1][0], x, what)
            else:
                bands.append((x, x, what))
        return bands

    def test_the_colour_cell_is_first_at_the_bars_width_and_the_name_carries_the_arrows(self):
        view, header = self.view, self.view.header()
        color = sidebar_model.COLOR_COLUMN
        self.assertEqual(2, self.model.columnCount())
        self.assertEqual((0, 1), (header.visualIndex(color), header.visualIndex(0)))
        self.assertEqual(theme.ui_px(amazetheme.drawn_sidebar()["bar"]), header.sectionSize(color))
        self.assertEqual(view.viewport().width() - header.sectionSize(color), header.sectionSize(0))
        self.assertEqual(0, view.treePosition(), "the arrows are not in the name's column")
        self.assertTrue(view.rootIsDecorated(), "a list with rows under rows has no arrow column")
        flat = QtGui.QStandardItemModel()
        for name in ("All", "Wood"):
            flat.appendRow([QtGui.QStandardItem(name), QtGui.QStandardItem()])
        self.assertFalse(self._view(flat).rootIsDecorated(), "a flat list reserves an arrow column")

    def test_a_rows_colour_is_its_colour_cells_background_and_no_other_cell_data(self):
        self.model.set_color(self.loc, "#ff8000")
        cell = self.model.index_of(self.loc).siblingAtColumn(sidebar_model.COLOR_COLUMN)
        self.assertEqual("#ff8000", cell.data(QtCore.Qt.ItemDataRole.BackgroundRole).color().name())
        self.assertIsNone(cell.data(QtCore.Qt.ItemDataRole.DisplayRole))
        plain = self.model.index_of(self.other).siblingAtColumn(sidebar_model.COLOR_COLUMN)
        self.assertIsNone(plain.data(QtCore.Qt.ItemDataRole.BackgroundRole))
        self.assertEqual(0, self.model.rowCount(cell), "rows hang under a colour cell")

    def test_one_place_on_a_row_opens_and_closes_it_and_every_other_place_chooses_it(self):
        self._scanned(self.loc, _child(self.loc, "A"))
        view = self.view
        view.expandAll()
        for path in (self.loc, _child(self.loc, "A")):
            bands = self._press_bands(view, self.model.index_of(path))
            kinds = [what for _a, _b, what in bands]
            with self.subTest(row=path.rstrip("/").rsplit("/", 1)[-1], bands=bands):
                self.assertEqual(1, kinds.count("toggles"), "the row opens and closes in other than one place")
                self.assertNotIn("nothing", kinds, "a press on the row does nothing somewhere")
                self.assertNotIn("toggles chooses", kinds)
                self.assertTrue(all(kind in ("toggles", "chooses") for kind in kinds))

    def test_the_user_choosing_a_row_is_one_signal_by_mouse_and_by_keyboard_only(self):
        view, model = self.view, self.model
        chosen = []
        view.row_chosen.connect(lambda index: chosen.append(index.data(model.BrowseRole)))
        view.highlight(model.index_of(self.loc))
        self.assertEqual([], chosen, "the app's own move counted as the user's choice")
        other = view.visualRect(model.index_of(self.other)).center()
        QtTest.QTest.mouseClick(view.viewport(), QtCore.Qt.MouseButton.LeftButton,
                                QtCore.Qt.KeyboardModifier.NoModifier, other)
        self.assertEqual([self.other], chosen)
        QtTest.QTest.keyClick(view, QtCore.Qt.Key.Key_Up)
        self.assertEqual([self.other, self.loc], chosen, "the Up key did not choose the row above")
        self.assertEqual([self.loc], [i.data(model.BrowseRole) for i in view.selected_rows()])

    def test_a_repaint_reads_each_rows_name_once(self):
        reads = []

        class Counted(QtGui.QStandardItemModel):
            def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
                if role == QtCore.Qt.ItemDataRole.DisplayRole:
                    reads.append(index.row())
                return super().data(index, role)
        names = Counted()
        for name in ("All", "Wood", "Metal"):
            names.appendRow(QtGui.QStandardItem(name))
        view = self._view(names)
        view.viewport().grab()    # a first paint, so the next one is a repaint and nothing else
        del reads[:]
        view.viewport().grab()
        self.assertEqual([0, 1, 2], sorted(reads),
                         "a repaint read a row's name more than once, or not at all")

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

    def test_a_flat_sidebar_paints_its_rows_as_the_list_did(self):
        flat = QtGui.QStandardItemModel()
        for name in ("All", "Wood", "Metal"):
            flat.appendRow(QtGui.QStandardItem(name))
        views = [self._styled_as_houdini(self._view(flat, kind))
                 for kind in (QtWidgets.QListView, sidebar.SidebarTreeView)]
        for view in views:    # same state in both: row 1 current and selected, neither focused
            view.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
            view.clearFocus()
            view.selectionModel().setCurrentIndex(
                flat.index(1, 0), QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        test_support.pump_until(lambda: False, timeout=0.05)
        a, b = (view.viewport().grab().toImage() for view in views)
        self.assertEqual(a.size(), b.size(), "premise: the two viewports differ in size")
        ends = {self._rows_end(view) for view in views}
        self.assertEqual(1, len(ends), "premise: the rows end at different heights: %s" % ends)
        end = int(ends.pop() * a.devicePixelRatio())
        rows = sorted({y for y in range(end) for x in range(a.width())
                       if a.pixel(x, y) != b.pixel(x, y)})
        self.assertEqual([], rows[:5], "a flat sidebar does not paint its rows as the list "
                         "did (%d pixel rows)" % len(rows))

    def test_the_styles_row_colours_fill_the_space_below_the_rows(self):
        self._scanned(self.loc)
        view, loc = self._styled_as_houdini(self.view), self.model.index_of(self.loc)
        host = view.parentWidget()
        host.setStyleSheet(NO_EMPTY_AREA_ROW_COLORS)    # the ground with no row colours, whatever the palette
        test_support.pump_until(lambda: False, timeout=0.05)
        plain = self._column(view)
        host.setStyleSheet(EMPTY_AREA_ROW_COLORS)
        test_support.pump_until(lambda: False, timeout=0.05)
        rest = self._rows_end(view)
        self.assertNotEqual(self._below(plain, rest), self._below(self._column(view), rest),
                            "with the folder closed the row colours stop at the last row")
        view.expand(loc)
        end = self._rows_end(view)
        self.assertGreater(end, rest, "premise: opening the folder added no rows")
        self.assertNotEqual(self._below(plain, end), self._below(self._column(view), end),
                            "with the folder open the row colours stop at the last row")

    def test_the_view_turns_qts_open_and_close_animation_off(self):
        with mock.patch.object(sidebar.SidebarTreeView, "setAnimated") as asked:
            view = sidebar.SidebarTreeView()
            self.addCleanup(view.deleteLater)
        asked.assert_called_once_with(False)    # Houdini's style builds a QTreeView with it on
        self.assertFalse(self.view.isAnimated(), "the sidebar animates a folder opening and closing")

    @staticmethod
    def _edge_column(view) -> list:
        """The viewport's pixels down a column right of every row's text: the row colours alone."""
        image = view.viewport().grab().toImage()
        return [image.pixel(image.width() - 3, y) for y in range(image.height())]

    def test_a_folder_opens_and_closes_in_one_frame_and_the_row_colours_stay(self):
        self._scanned(self.loc)
        loc = self.model.index_of(self.loc)
        self.assertGreater(self.model.rowCount(loc), 0, "premise: the location has no folders to show")
        animating = QtWidgets.QAbstractItemView.State.AnimatingState
        plain = self._styled_as_houdini(self._view(self.model, QtWidgets.QTreeView))
        plain.setAnimated(True)    # as Houdini's style builds every tree view
        still = self._edge_column(plain)
        plain.expand(loc)
        test_support.pump_until(lambda: False, timeout=0.1)    # part of the way through Qt's 250 ms
        self.assertEqual(animating, plain.state(), "premise: an animated tree is not animating")
        self.assertNotEqual(still, self._edge_column(plain),
                            "premise: the column read does not see row colours that move")
        view = self._styled_as_houdini(self.view)
        still = self._edge_column(view)
        self.assertGreater(len(set(still)), 1, "premise: the column holds one colour, no row colours")
        for change, word in ((view.expand, "opened"), (view.collapse, "closed")):
            change(loc)
            self.assertEqual(word == "opened", view.isExpanded(loc), "premise: the folder never %s" % word)
            self.assertNotEqual(animating, view.state(), "the folder %s with an animation" % word)
            self.assertEqual(still, self._edge_column(view),
                             "the row colours moved in the frame the folder %s" % word)
            test_support.pump_until(lambda: False, timeout=0.1)
            self.assertEqual(still, self._edge_column(view),
                             "the row colours moved after the folder %s" % word)

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

    def test_reveal_expands_the_parents_and_selects_the_folder(self):
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

    def test_a_click_before_the_read_finishes_keeps_the_row_clicked(self):
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
        self.assertEqual([self.other], [i.data(model.BrowseRole) for i in view.selected_rows()],
                         "the remembered folder replaced the clicked row's selection")
        self.assertEqual(self.other, view.currentIndex().data(model.BrowseRole))


class TheFileTabBrowsesSubfolders(unittest.TestCase):
    """A subfolder is browsed like a location and never moved, removed or relocated as one."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.folders = self.panel.pane.file_folders_model
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

    def _select_row(self, index):
        view = self.panel.cat_list
        view.selectionModel().setCurrentIndex(
            index, QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.panel.pane.sidebar.show_row()
        QtWidgets.QApplication.processEvents()

    def test_a_click_on_a_subfolder_browses_it(self):
        self._select_row(self.sub)
        files = self.panel.pane.file_files_model
        self.assertEqual(_child(self.loc, "c_sub"), files.browsing())
        self.assertEqual(_child(self.loc, "c_sub"), self.panel.pane.prefs.last_file_folder)

    def test_a_subfolder_is_never_removed_moved_or_relocated_as_a_location(self):
        section = self.panel.pane.sections["file"]
        self.assertFalse(self.folders.movable(self.sub), "a subfolder can be dragged")
        before = list(self.folders._folders())
        self._select_row(self.sub)
        self.assertEqual([], self.panel.pane.files.remove_locations(),
                         "removing with a subfolder selected unregistered a location")
        self.panel.pane.files.locate_folder(self.folders)
        self.assertEqual(before, list(self.folders._folders()),
                         "Locate on a subfolder's row changed a location's path")
        self.assertEqual(self.folders.index_of(self.loc),
                         sidebar_model.top_level(self.sub), "`top_level` of a subfolder is not its location's row")

    def test_locate_and_add_on_a_folder_already_a_location_show_a_message(self):
        import hou
        from amaze import messages
        second = self.folders._folders()[1].rstrip("/")    # the picker returns no trailing separator
        before = list(self.folders._folders())
        self._select_row(self.folders.index_of(self.loc))
        ui = mock.Mock()
        ui.selectFile.return_value = second
        with mock.patch.object(hou, "ui", ui, create=True):
            self.panel.pane.files.locate_folder(self.folders)
            self.assertEqual(messages.LOCATION_ALREADY_ADDED, ui.displayMessage.call_args[0][0],
                             "a Locate onto a location showed a message other than `LOCATION_ALREADY_ADDED`")
            ui.displayMessage.reset_mock()
            self.panel.pane.files.add_location()
            self.assertTrue(ui.displayMessage.called, "adding a location twice showed no message")
            self.assertEqual(messages.LOCATION_ALREADY_ADDED, ui.displayMessage.call_args[0][0])
        self.assertEqual(before, list(self.folders._folders()))

    def test_a_subfolders_menu_greys_the_location_entries(self):
        section = self.panel.pane.sections["file"]
        location = self.folders.index_of(self.loc)
        self.assertTrue(section.on_a_location([location], location), "premise: a location row")
        self.assertFalse(section.on_a_location([self.sub], self.sub),
                         "Locate, Rename, Remove and Label stay enabled on a subfolder")
        greyed = {entry.label for entry in section.SIDEBAR_MENU
                  if entry.needs == "on_a_location"}
        self.assertEqual({"Locate", "Rename", "Remove", "Label"}, greyed,
                         "the location entries are not the ones the manual names")

    def test_the_file_tab_reopens_on_a_remembered_subfolder(self):
        sub = _child(self.loc, "b_sub")
        self.panel.section_tabs.setChecked("material")
        self.panel.pane.prefs.last_file_folder = sub
        self.panel.section_tabs.setChecked("file")
        QtWidgets.QApplication.processEvents()
        self.assertEqual(sub, self.panel.pane.file_files_model.browsing(),
                         "the grid shows another folder")
        view, model = self.panel.cat_list, self.folders
        model.data(model.index_of(self.loc), COUNT)
        self.assertTrue(test_support.pump_until(lambda: view.currentIndex().data(model.BrowseRole) == sub),
                        "the sidebar never made the remembered subfolder current")

    def test_the_live_current_index_keeps_its_parent(self):
        view = self.panel.cat_list
        view.setCurrentIndex(self.sub)
        live = grid_columns.live_current_index(view)
        self.assertEqual(self.sub, live, "the live index lost the subfolder's parent")


def _base_style_options(source: str) -> list:
    """The lines of `source` that build the base `QStyleOption`, not one of its subclasses."""
    import ast
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            called = node.func
            name = called.attr if isinstance(called, ast.Attribute) else getattr(called, "id", "")
            if name == "QStyleOption":
                found.append(node.lineno)
    return found


class NoCodeBuildsTheBaseStyleOption(unittest.TestCase):
    """Houdini's style is asked only as Qt's own widgets ask it. ▸r/tree-views"""

    def test_no_module_builds_the_base_style_option(self):
        """No test reaches Houdini's style, so the source is read: the suite runs on Qt's own."""
        package = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        found, read = [], 0
        for root, dirs, files in os.walk(package):
            dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__")]
            for name in sorted(n for n in files if n.endswith(".py")):
                path = os.path.join(root, name)
                with open(path, encoding="utf-8") as handle:
                    lines = _base_style_options(handle.read())
                read += 1
                found += ["%s:%d" % (test_support.posix_relpath(path, package), line)
                          for line in lines]
        self.assertGreater(read, 100, "the walk read almost nothing")
        self.assertEqual([], found, "a base QStyleOption is built here; give the style the "
                                    "option class Qt's own widget passes for that element")

    def test_the_scan_tells_the_base_class_from_its_subclasses(self):
        source = ("a = QtWidgets.QStyleOptionViewItem()\nb = QtWidgets.QStyleOption()\n"
                  "c = QStyleOption(1)\nd = QStyleOptionHeader()\n")
        self.assertEqual([2, 3], _base_style_options(source))


class EveryModelThatUnfoldsIsASidebarModel(unittest.TestCase):
    """The sidebar keeps a list's open rows by SIDEBAR_KEY_ROLE and finds them with `index_of`."""

    def test_every_model_declaring_unfolds_is_a_sidebar_model(self):
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
        from amaze.core import sidebar_model
        for cls in unfolding:
            self.assertTrue(
                issubclass(cls, sidebar_model.SidebarModel),
                "%s unfolds but is no SidebarModel, so it may not answer the key role and "
                "index_of that the sidebar keeps its open rows by" % cls.__name__)


class EverySectionsSidebarIsTheOneView(unittest.TestCase):
    """Each section puts its model in the same view; none changes how the view paints."""

    def test_no_section_changes_the_view_its_row_painter_or_its_row_colours(self):
        panel = test_support.fixture_panel(self)
        panel.resize(900, 700)
        panel.show()
        self.addCleanup(panel.hide)
        steps = [(key, lambda key=key: panel.section_tabs.setChecked(key))
                 for key in test_support.ALL_SECTION_KEYS + ("material",)]
        steps.append(("online", panel.pane.enter_online))
        first = None
        for name, show in steps:
            show()
            test_support.pump_until(lambda: False, timeout=0.05)
            view = panel.cat_list
            now = (view, type(view), view.itemDelegate(), view.alternatingRowColors(),
                   view.isAnimated(), view.styleSheet(), view.indentation())
            first = first or now
            self.assertEqual(first, now, "%s changed the sidebar's view or its painting" % name)
        self.assertIs(sidebar.SidebarTreeView, first[1])
        self.assertTrue(first[3], "the sidebar's row colours are off")
        self.assertEqual("", first[5], "the sidebar has a style sheet of its own")
        self.assertNotIn("paintEvent", vars(sidebar.SidebarTreeView),
                         "the sidebar paints itself, where Qt's tree view should")

    @staticmethod
    def _rows(model, parent=QtCore.QModelIndex()):
        """Every row the list holds now, its read subfolders included, parents first."""
        for row in range(model.rowCount(parent)):
            index = model.index(row, 0, parent)
            yield index
            if getattr(model, "unfolds", False):    # hasChildren is private on a QAbstractListModel
                yield from EverySectionsSidebarIsTheOneView._rows(model, index)

    def test_every_list_keys_each_row_and_finds_the_row_again_by_its_key(self):
        """Each row answers SIDEBAR_KEY_ROLE, "" on All; `index_of` gives that row back."""
        from amaze.core import matx_sources
        from amaze import sections
        from amaze.sections import file as file_section, online as online_section, base as section_base
        panel = test_support.fixture_panel(self)
        steps = [(key, lambda key=key: panel.section_tabs.setChecked(key))
                 for key in test_support.ALL_SECTION_KEYS]
        steps.append(("online", panel.pane.enter_online))
        for name, show in steps:
            show()
            test_support.pump_until(lambda: False, timeout=0.05)
            model = panel.cat_list.model()
            if name == "file":    # read every location, so its subfolder rows exist
                for row in range(1, model.rowCount()):
                    model.data(model.index(row, 0), COUNT)
                self.assertTrue(test_support.pump_until(
                    lambda: any(index.parent().isValid() for index in self._rows(model))),
                    "premise: the fixture location's subfolder never got a row")
            if name == "online":    # the suite blocks the network: one record gives the list a row
                online = panel.pane.matx_online_model
                previous = online._all
                online._all = [matx_sources.MatxRecord(
                    source=online._source_filter, uid="key-probe", title="Key Probe",
                    category="Metal")]
                self.addCleanup(setattr, online, "_all", previous)
                model.refresh()
            section = panel.pane.active_section()
            rows = list(self._rows(model))
            if name in ("material", "file", "online"):    # one of each list class has rows below All
                self.assertGreater(len(rows), 1, "premise: the %s list has only All" % name)
            for index in rows:
                with self.subTest(section=name, row=index.row(), label=index.data()):
                    key = index.data(category.SIDEBAR_KEY_ROLE)
                    self.assertIsInstance(key, str, "the row does not answer the key role")
                    all_row = index == model.index(0, 0)
                    self.assertEqual(all_row, key == "", "only the All row is keyed \"\"")
                    self.assertEqual(index, model.index_of(key),
                                     "index_of does not give back the row keyed %r" % key)
                    self.assertEqual(key, section.sidebar_key(index))
            if name == "file":
                for index in rows:
                    with self.subTest(location=index.data()):
                        self.assertEqual(index.data(model.PathRole) or "",
                                         section.location_key(index),
                                         "a location action would act on a row that is no location")
        classes = list(sections.SECTION_CLASSES) + [online_section.OnlineContext]
        for cls in classes:
            for klass in cls.__mro__:
                if klass in (section_base.Section, object):
                    continue
                for method in ("sidebar_key", "_row_keyed"):
                    self.assertNotIn(method, vars(klass),
                                     "%s keys its sidebar rows its own way" % klass.__name__)


class EverySidebarListAnswersTheReorder(unittest.TestCase):
    """Each sidebar list moves its own rows in view rows; Section holds the reorder methods once."""

    CALLS = ("movable", "move_row", "commit_order")
    SECTION_CALLS = ("sidebar_movable", "move_sidebar_row", "sidebar_order_snapshot",    # none may come back
                     "restore_sidebar_order", "commit_sidebar_order")

    def test_the_list_in_the_view_answers_the_three_calls(self):
        panel = test_support.fixture_panel(self)
        steps = [(key, lambda key=key: panel.section_tabs.setChecked(key))
                 for key in test_support.ALL_SECTION_KEYS]
        steps.append(("online", panel.pane.enter_online))
        for name, show in steps:
            show()
            test_support.pump_until(lambda: False, timeout=0.05)
            model = panel.cat_list.model()
            for call in self.CALLS:
                with self.subTest(section=name, call=call):
                    self.assertTrue(callable(getattr(model, call, None)),
                                    "the %s list has no %s" % (name, call))
            if name == "online":
                for row in range(model.rowCount()):
                    self.assertFalse(model.movable(model.index(row, 0)),
                                     "an online category row can be dragged")

    def test_no_section_defines_its_own_reorder(self):
        from amaze import sections
        from amaze.sections import file as file_section, online as online_section, base as section_base
        for cls in list(sections.SECTION_CLASSES) + [online_section.OnlineContext]:
            for klass in cls.__mro__:
                if klass is object:
                    continue
                for method in self.SECTION_CALLS:
                    self.assertNotIn(method, vars(klass),
                                     "%s reorders its sidebar its own way" % klass.__name__)

    def test_a_category_list_moves_a_shown_row_by_view_rows_past_a_hidden_one(self):
        prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        model = category.Categories(preferences=prefs)
        model._categories[:] = ["_All", "a", "hidden", "b", "c"]
        proxy = category.CategoriesSidebarProxy()
        proxy.setSourceModel(model)
        model.set_renderer_filter("karma")    # empty categories hide only under a renderer filter
        counts = lambda name: 0 if name == "hidden" else 1
        with mock.patch.object(model, "_category_count", side_effect=counts):
            proxy.invalidateFilter()
            self.assertEqual(["All", "a", "b", "c"],
                             [proxy.index(row, 0).data() for row in range(proxy.rowCount())],
                             "premise: the empty category is not hidden between two shown ones")
            self.assertFalse(proxy.movable(proxy.index(0, 0)), "All can be dragged")
            self.assertTrue(all(proxy.movable(proxy.index(row, 0)) for row in (1, 2, 3)))
            before = list(model._categories)
            self.assertTrue(proxy.move_row(proxy.index(3, 0), 0), "c did not move")
            self.assertEqual(["_All", "c", "a", "hidden", "b"], list(model._categories),
                             "the move did not map view rows to stored rows, or went above All")
            with mock.patch.object(model, "save") as save:
                proxy.commit_order()
            save.assert_called_once_with()
            model.restore_order(before)
            self.assertEqual(["_All", "a", "hidden", "b", "c"], list(model._categories))

    def test_in_file_a_location_moves_and_a_subfolder_the_scene_row_and_All_do_not(self):
        panel = test_support.fixture_panel(self)
        model = panel.pane.file_folders_model
        loc = model.registered_at(model._offset())
        os.makedirs(os.path.join(loc, "a_sub"), exist_ok=True)
        second = test_support.fresh_files_folder(self)
        self.assertTrue(model.add_folder(second), "premise: the second location was not added")
        panel.section_tabs.setChecked("file")
        QtWidgets.QApplication.processEvents()
        self.assertIs(model, panel.cat_list.model())
        _shown(model, loc)
        sub = model.index_of(_child(loc, "a_sub"))
        self.assertTrue(sub.isValid(), "premise: the location's subfolder has no row")
        self.assertTrue(model.is_scene_row(model.index(1, 0)), "premise: no scene row")
        self.assertFalse(model.movable(model.index(0, 0)), "All can be dragged")
        self.assertFalse(model.movable(model.index(1, 0)), "the scene row can be dragged")
        self.assertFalse(model.movable(sub), "a subfolder can be dragged")
        first = model.index(model._offset(), 0)
        self.assertTrue(model.movable(first), "a location cannot be dragged")
        before = list(model._folders())
        self.assertTrue(model.move_row(model.index(model._offset() + 1, 0), 0),
                        "the second location did not move")
        self.assertEqual(list(reversed(before[:2])) + before[2:], list(model._folders()),
                         "the move went above the scene row, or did not move to the first location")
        with mock.patch.object(locations, "commit_registered_order") as commit:
            model.commit_order()
        commit.assert_called_once_with(model.preferences)
        model.restore_order(before)
        self.assertEqual(before, list(model._folders()))


class EverySidebarListIsOneTreeModel(unittest.TestCase):
    """Categories, the folder tree and the online list share one tree model and keep its contract."""

    def test_every_list_is_a_sidebar_model_and_the_folder_tree_has_no_tree_of_its_own(self):
        from amaze.core import matx_library, sidebar_model
        for cls in (category.Categories, file_library.FileFolders, matx_library.MatxSidebarModel):
            self.assertTrue(issubclass(cls, sidebar_model.SidebarModel),
                            "%s is not a SidebarModel" % cls.__name__)
        for name in ("index", "parent", "rowCount", "columnCount", "hasChildren"):
            self.assertNotIn(name, vars(folders.FolderTreeModel),
                             "the folder tree defines its own %s" % name)

    def test_the_base_imports_before_the_category_list_that_subclasses_it(self):
        """The base loads first, though category.py subclasses it and it reads category's roles."""
        import importlib
        import sys
        from amaze import core
        names = ("sidebar_model", "category")
        loaded = {name: sys.modules.pop("amaze.core." + name) for name in names}
        self.addCleanup(lambda: [(sys.modules.__setitem__("amaze.core." + name, module),
                                  setattr(core, name, module)) for name, module in loaded.items()])
        for name in names:
            delattr(core, name)
        base = importlib.import_module("amaze.core.sidebar_model")
        listed = importlib.import_module("amaze.core.category")
        self.assertTrue(issubclass(listed.Categories, base.SidebarModel))

    def test_a_flat_lists_rows_carry_the_flags_of_a_qt_list_models_rows(self):
        """Qt's list model marks its rows as never having children; a flat sidebar list does too."""
        from amaze.core import matx_library

        class _QtList(QtCore.QAbstractListModel):
            def rowCount(self, parent=QtCore.QModelIndex()):
                return 0 if parent.isValid() else 2

            def data(self, index, role=0):
                return None
        qt_list = _QtList()
        listed = qt_list.flags(qt_list.index(1, 0))
        self.assertTrue(listed & QtCore.Qt.ItemFlag.ItemNeverHasChildren,
                        "premise: Qt's list model does not mark its rows")
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        categories = category.Categories(test_support.fixture_prefs(self))
        online = _OnlineCategories()
        online.names = ["Metal"]
        matx = matx_library.MatxSidebarModel(online)
        for model in (categories, matx):
            for row in (0, 1):
                self.assertEqual(listed, model.flags(model.index(row, 0)),
                                 "%s row %d" % (type(model).__name__, row))
        tree, _prefs, _roots = _model(self, {"A": {}})
        self.assertFalse(tree.flags(tree.index(1, 0)) & QtCore.Qt.ItemFlag.ItemNeverHasChildren,
                         "a folder is marked as never having subfolders")

    def test_qts_model_checker_finds_nothing_in_a_category_list_or_through_its_proxy(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        model = category.Categories(test_support.fixture_prefs(self))
        model._categories[:] = ["_All", "Wood", "_WIP", "Metal", "Glass"]
        proxy = category.CategoriesSidebarProxy()
        proxy.setSourceModel(model)
        complaints = _checker_complaints(self, model, proxy)
        model.check_add_category("Stone")
        model.rename_category("Glass", "Crystal")
        self.assertTrue(model.move_category(4, 1), "premise: the move was refused")
        model.remove_category("Metal")
        model.set_renderer_filter("karma")    # every category is empty, so the proxy hides them
        proxy.refresh()
        self.assertEqual(1, proxy.rowCount(), "premise: the proxy hides no empty category")
        model.set_renderer_filter("")
        proxy.refresh()
        model.sort_categories()
        self.assertEqual(["", "Crystal", "Stone", "_WIP", "Wood"],
                         [proxy.index(row, 0).data(category.SIDEBAR_KEY_ROLE)
                          for row in range(proxy.rowCount())], "premise: not the rows changed")
        self.assertEqual([], complaints, "QAbstractItemModelTester reported problems")

    def test_qts_model_checker_finds_nothing_in_the_online_list(self):
        from amaze.core import matx_library
        online = _OnlineCategories()
        model = matx_library.MatxSidebarModel(online)
        complaints = _checker_complaints(self, model)
        online.names = ["Metal", "Wood", "Fabric"]
        online.modelReset.emit()
        self.assertEqual(4, model.rowCount(), "premise: the categories are not rows")
        online.names = ["Wood"]
        online.modelReset.emit()
        self.assertEqual(["All", "Wood"], [model.index(row, 0).data() for row in range(2)])
        self.assertEqual([], complaints, "QAbstractItemModelTester reported problems")


class EverySectionIsEnteredByOneActivate(unittest.TestCase):
    """Section holds `activate` and the colour methods once; each section keeps its entry order."""

    ASSET_ORDER = ["setModel", "bind_grid_views", "sync_list_columns", "show_progress",
                   "select_default_row"]
    ORDER = {    # the views show the section's models, columns included, before its own hook runs
        "file": ["refresh_counts", "setModel", "bind_grid_views", "sync_list_columns",
                 "show_progress", "highlight", "show_row"],
        "online": ["setModel", "bind_grid_views", "sync_list_columns", "show_progress", "reload"],
    }

    def test_no_section_defines_its_own_activate_or_colour_methods(self):
        from amaze import sections
        from amaze.sections import file as file_section, online as online_section, base as section_base
        for cls in list(sections.SECTION_CLASSES) + [online_section.OnlineContext]:
            for klass in cls.__mro__:
                if klass in (section_base.Section, object):
                    continue
                for method in ("activate", "sidebar_colour", "set_sidebar_colour"):
                    self.assertNotIn(method, vars(klass),
                                     "%s defines its own %s" % (klass.__name__, method))
                if "select_sidebar_key" in vars(klass):
                    self.assertIs(file_section.FolderSection, klass,
                                  "%s selects a sidebar row its own way" % klass.__name__)

    @staticmethod
    def _recorded(panel, context) -> list:
        """The watched calls `context.activate()` makes itself, in order; calls inside them are not."""
        calls, depth = [], [0]
        pane = panel.pane
        watched = ((panel.cat_list, "setModel"), (panel, "bind_grid_views"),
                   (pane, "show_progress"), (panel, "sync_list_columns"),
                   (pane.file_folders_model, "refresh_counts"),
                   (pane.matx_online_model, "reload"), (pane.sidebar, "highlight"),
                   (pane.sidebar, "select_default_row"), (pane.sidebar, "show_row"))
        with contextlib.ExitStack() as stack:
            for owner, name in watched:
                def call(*args, _run=getattr(owner, name), _name=name, **kwargs):
                    if not depth[0]:
                        calls.append(_name)
                    depth[0] += 1
                    try:
                        return _run(*args, **kwargs)
                    finally:
                        depth[0] -= 1
                stack.enter_context(mock.patch.object(owner, name, side_effect=call))
            context.activate()
        return calls

    def test_each_section_runs_its_entry_calls_in_its_own_order(self):
        panel = test_support.fixture_panel(self)
        steps = [(key, lambda key=key: panel.section_tabs.setChecked(key))
                 for key in test_support.ALL_SECTION_KEYS]
        steps.append(("online", panel.pane.enter_online))
        for name, show in steps:
            show()
            test_support.pump_until(lambda: False, timeout=0.05)
            context = panel.pane.online_context if name == "online" else panel.pane.sections[name]
            with self.subTest(section=name):
                self.assertEqual(self.ORDER.get(name, self.ASSET_ORDER),
                                 self._recorded(panel, context))
                self.assertIs(getattr(panel.pane, context.sidebar_attr), panel.cat_list.model(),
                              "the section did not put its own list in the sidebar")


class TheSidebarListStoresARowsColour(unittest.TestCase):
    """A section asks its sidebar list for a row's colour; each list keeps it in its own store."""

    def test_a_category_list_keeps_a_colour_in_the_sections_database(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        prefs = test_support.fixture_prefs(self)
        model = category.Categories(prefs)
        model.check_add_category("Metal")
        proxy = category.CategoriesSidebarProxy()
        proxy.setSourceModel(model)
        proxy.set_color("Metal", "#4af2a1")
        self.assertEqual("#4af2a1", proxy.color_of("Metal"))
        self.assertEqual("#4af2a1", model._doc().table(category.SECTION)["Metal"].get("color"),
                         "the colour is not in the section's database")
        self.assertEqual("#4af2a1", category.Categories(prefs).color_of("Metal"))
        proxy.set_color("Metal", "")
        self.assertEqual("", proxy.color_of("Metal"))
        self.assertNotIn("color", model._doc().table(category.SECTION)["Metal"])

    def test_the_folder_list_keeps_a_colour_in_the_location_record_and_none_on_a_subfolder(self):
        from amaze import sections
        from amaze.sections import file as file_section, online as online_section, base as section_base
        model, prefs, roots = _model(self, {"A": {}})
        loc = roots[0]
        repainted = []
        model.dataChanged.connect(
            lambda first, _last, *_roles: repainted.append(first.data(category.SIDEBAR_KEY_ROLE)))
        model.set_color(loc, "#ff8000")
        self.assertEqual("#ff8000", model.color_of(loc))
        self.assertEqual("#ff8000", locations.record(prefs, loc).get("color"),
                         "the colour is not in the location's record")
        self.assertIn(loc, repainted, "the location's row was not repainted")
        _shown(model, loc)
        self.assertTrue(test_support.pump_until(
            lambda: model.index_of(_child(loc, "A")).isValid()), "premise: the subfolder has no row")
        sub = model.index_of(_child(loc, "A"))
        self.assertEqual("", sub.data(category.SIDEBAR_COLOR_ROLE), "a subfolder paints a colour")
        section = file_section.FileSection.__new__(file_section.FileSection)
        with mock.patch.object(file_section.FileSection, "_p", lambda _s, _name: model):
            self.assertEqual("", section.colour_key(sub), "a subfolder row takes a colour")
            self.assertEqual(loc, section.colour_key(model.index_of(loc)))
        model.set_color(loc, "")
        self.assertNotIn("color", locations.record(prefs, loc))

    def test_sort_by_name_saves_through_the_lists_commit_order(self):
        """The sort and the drag reorder save a File order the same one way."""
        from amaze import sections
        from amaze.sections import file as file_section, online as online_section, base as section_base
        prefs = test_support.fixture_prefs(self)
        for layout in ({}, {}):
            prefs.add_file_folder(_tree(self, layout))
        model = file_library.FileFolders(prefs)
        roots = list(model._folders())
        prefs.set_file_folder_name(roots[0], "b")
        prefs.set_file_folder_name(roots[1], "a")
        section = file_section.FileSection.__new__(file_section.FileSection)
        with mock.patch.object(file_section.FileSection, "_p", lambda _s, _name: model), \
                mock.patch.object(file_section.FileSection, "shown_sidebar_key", lambda _s: ""), \
                mock.patch.object(file_section.FileSection, "select_sidebar_key"), \
                mock.patch.object(file_section.FileSection, "pane", mock.Mock(prefs=prefs), create=True), \
                mock.patch.object(model, "commit_order") as commit:
            section.menu_sort_locations([], None)
        commit.assert_called_once_with()
        self.assertEqual([roots[1], roots[0]], list(model._folders()), "premise: nothing was sorted")


if __name__ == "__main__":
    unittest.main()
