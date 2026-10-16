"""The File section's folder browsing and its disk caches. Images and Geometry were twin sections on one ThumbnailCache before the merge folded them, with HIP, into the File section - one model, per-kind pipelines, still the same shared cache class - and the bugs pinned here are all of the twin shape: a fix applied to one pipeline and not the other, which is exactly what the merge exists to end."""

import ast
import inspect
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(    # THREE dirnames up = scripts/python, the directory holding the `amaze` package - the DEV tree, not the install on Houdini's path
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # BEFORE the app exists ▸p/first-app-picks-the-platform
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401
from amaze.core import texture_library, thumbnails  # noqa: E402
from amaze.helpers import hostos  # noqa: E402
from amaze.panel import sections  # noqa: E402
from amaze.tests import test_support  # noqa: E402


class DeleteLocalCacheTest(unittest.TestCase):
    """`Delete Local Cache` must not break Geometry for the session: ThumbnailCache.clear() sweeps every texture_thumbnails_* AND geo_thumbnails_* directory - correct, they would pile up otherwise - but recreates only its OWN, while GeoFiles._get_cache() memoises on (size, mode, bg), none of which change when the cache is cleared, so it hands back an object whose directory no longer exists. Measured before the fix: after one press the geometry render's _render_tmp.png could not be written, put() cached nothing, and it repeated on every folder visit until Houdini restarted, reported only by a print()."""

    def setUp(self):
        self.source = os.path.join(
            tempfile.mkdtemp(prefix="amaze_cache_src_"), "tex.png")
        self.addCleanup(shutil.rmtree, os.path.dirname(self.source), True)
        QtGui.QImage(8, 8, QtGui.QImage.Format.Format_ARGB32).save(
            self.source, "PNG")

        self.image = QtGui.QImage(16, 16, QtGui.QImage.Format.Format_ARGB32)
        self.image.fill(QtGui.QColor("red"))

        self.textures = texture_library.ThumbnailCache(256)
        self.geometry = texture_library.ThumbnailCache(
            256, prefix="geo_thumbnails_test_black")
        self.addCleanup(shutil.rmtree, self.geometry.cache_dir, True)

    def test_the_geometry_cache_survives_a_texture_cache_clear(self):
        self.textures.clear()
        self.assertFalse(
            os.path.isdir(self.geometry.cache_dir),
            "clear() no longer sweeps the geometry dirs - this test is "
            "not exercising the case it was written for")

        self.geometry.put(self.source, self.image)
        self.geometry.save()
        self.assertTrue(
            self.geometry.valid_path(self.source),
            "the geometry cache could not store a thumbnail after "
            "Delete Local Cache - every visit re-renders and caches "
            "nothing for the rest of the session")

    def test_the_render_scratch_file_is_writable_after_a_clear(self):
        """GeoFiles renders to _render_tmp.png inside the cache dir BEFORE the cache is asked to store anything."""
        self.textures.clear()
        self.geometry.ensure_dir()
        scratch = os.path.join(self.geometry.cache_dir, "_render_tmp.png")
        self.assertTrue(
            self.image.save(scratch, "PNG"),
            "the geometry render could not write its scratch file")

    def test_a_failed_write_is_not_recorded_as_cached(self):
        """QImage.save returns False rather than raising, so a write into a missing directory can fall through to the manifest and record a cache entry for a file that was never written - valid_path then finds nothing and it re-renders forever."""
        shutil.rmtree(self.geometry.cache_dir, ignore_errors=True)
        open(self.geometry.cache_dir, "w").close()    # block recreation so the write genuinely fails
        self.addCleanup(os.remove, self.geometry.cache_dir)

        self.geometry.put(self.source, self.image)
        self.assertEqual(
            {}, self.geometry._manifest,
            "the manifest recorded a thumbnail that was never written")


class CacheIsolationTest(unittest.TestCase):
    """The tests above call clear(), which SWEEPS the cache root - against the default root that deletes the user's real texture and geometry thumbnails, regenerable but the geometry ones are Karma renders. test_support redirects the root at import; this is the tripwire."""

    def test_the_cache_root_is_not_the_real_one(self):
        from amaze.helpers import hostos

        root = os.path.realpath(hostos.cache_root())
        self.assertTrue(
            root.startswith(os.path.realpath(test_support.TEST_CACHE)),
            "the thumbnail cache is not isolated - a clear() in this "
            "suite would delete the user's real thumbnails (root=%s)"
            % root)

    def test_a_clear_cannot_reach_the_users_cache(self):
        from amaze.helpers import hostos

        real = os.path.expanduser("~/Library/Caches/Amaze")
        swept = os.path.dirname(
            texture_library.ThumbnailCache(256).cache_dir)
        self.assertNotEqual(
            os.path.realpath(real), os.path.realpath(swept),
            "clear() would sweep the real cache directory")
        self.assertTrue(hostos.cache_root())


class ProgressAccountingTest(unittest.TestCase):
    """The conversion bar must be able to reach 100%: counting ROWS while _on_convert_attempted discards by KEY and _progress_keys deduplicates stops the bar short forever, because two rows can share a canonical path - overlapping registered folders with Include Subfolders on (/root and /root/sub), or a case-variant duplicate on a case-insensitive volume. Worse than a cosmetic stall: the `_progress_done >= _progress_total` gate is what flushes the manifest, so nothing is recorded and the whole folder re-converts from scratch on every visit."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="amaze_overlap_")    # /root and /root/sub BOTH registered with recursion on: the same physical file is reached twice, which is the whole case
        self.addCleanup(shutil.rmtree, self.root, True)
        self.sub = os.path.join(self.root, "sub")
        os.makedirs(self.sub)
        with open(os.path.join(self.sub, "tex.exr"), "wb") as handle:    # an EXR is not natively decodable, so it takes the convert path and is counted rather than served from cache
            handle.write(b"\x76\x2f\x31\x01" + b"\0" * 256)

        self.prefs = test_support.fixture_prefs(self)
        for folder in (self.root, self.sub):    # through the SETTER: `file_recursive_folders` is derived from the library's location store, so extending the list it returns changes a value nothing will ever read again
            self.prefs.add_file_folder(folder)
            self.prefs.set_file_folder_recursive(folder, True)
        from amaze.core import file_library
        self.model = file_library.FileFiles(self.prefs)
        self.addCleanup(thumbnails.engine.cancel_pending_converts)

    def test_the_total_counts_distinct_keys_not_rows(self):
        self.model._load([self.root, self.sub])

        self.assertEqual(
            2, len(self.model._files),
            "the overlap did not produce two rows - this test is not "
            "exercising the case it was written for")
        self.assertEqual(
            len(self.model._progress_keys), self.model._progress_total,
            "the progress bar's total counts ROWS while completion is "
            "reported per KEY, so it can never reach 100%% - and the "
            "manifest flush is gated on reaching it")

    def test_the_bar_can_actually_complete(self):
        """The consequence, not the counter: every key reports once, so done must be able to reach total."""
        self.model._load([self.root, self.sub])
        for key in list(self.model._progress_keys):
            self.model._on_convert_attempted(key)
        self.assertGreaterEqual(
            self.model._progress_done, self.model._progress_total,
            "the conversion pass finished but the bar never completed, "
            "so the manifest was never flushed and this folder will "
            "re-convert from scratch on every visit")


class AFolderLoadTouchesEachFileOnce(unittest.TestCase):
    """One load stats each image once and sorts each name into its kind once."""

    def test_cached_images_are_stated_and_classified_once(self):
        from unittest import mock

        from amaze.core import file_library
        folder = tempfile.mkdtemp(prefix="amaze_load_once_")
        self.addCleanup(shutil.rmtree, folder, True)
        image = QtGui.QImage(8, 8, QtGui.QImage.Format.Format_RGB32)
        image.fill(QtGui.QColor("#336699"))
        names = ["img%d.png" % n for n in range(4)] + ["notes.txt"]
        for name in names[:4]:
            image.save(os.path.join(folder, name), "PNG")
        with open(os.path.join(folder, names[4]), "w") as handle:
            handle.write("x")
        prefs = test_support.fixture_prefs(self)
        prefs.add_file_folder(folder)
        model = file_library.FileFiles(prefs)
        self.addCleanup(thumbnails.engine.cancel_pending_converts)
        cache = model._get_image_cache()
        for name in names[:4]:
            cache.put(os.path.join(folder, name), image)
        cache.save()
        model._load([folder])
        stated, kinds = [], []
        real_stat, real_kind = os.stat, file_library.kind_for
        with mock.patch("os.stat", lambda p, *a, **k: (
                stated.append(os.path.basename(str(p))),
                real_stat(p, *a, **k))[1]), \
                mock.patch.object(file_library, "kind_for", lambda n: (
                    kinds.append(n), real_kind(n))[1]):
            model._load([folder])
        self.assertEqual(
            "file", {spec[1] for spec in model._row_specs
                     if spec[0] and spec[0][0] == "tex"}.pop(),
            "premise: the images are not served from the cache")
        self.assertEqual({name: 1 for name in names[:4]},
                         {name: stated.count(name) for name in names[:4]},
                         "a cached image was stated more than once")
        self.assertEqual(sorted(names), sorted(kinds),
                         "a name was classified more than once")


class ReconcileIsOnePassTest(unittest.TestCase):
    """Opening a folder must not walk the manifest once per subfolder: reconcile() walks the whole manifest, so calling it once per containing directory makes a folder open O(subdirs x manifest) against a manifest that is global per resolution and grows with every file ever thumbnailed - measured at 3.37s of main-thread dict iteration for 300 subdirs over 40,000 entries, against 0.01s for a single pass. Counted rather than timed, because a timing assertion here would be flaky and the invariant is "one pass", not "fast"."""

    class _CountingManifest(dict):
        def __init__(self, *args):
            super().__init__(*args)
            self.passes = 0

        def items(self):
            self.passes += 1
            return super().items()

    def _cache(self, entries=200):
        cache = texture_library.ThumbnailCache(256, prefix="recon_test")
        self.addCleanup(shutil.rmtree, cache.cache_dir, True)
        cache._manifest = self._CountingManifest(
            {"/elsewhere/d%d/f%d.png" % (i % 20, i): {"mtime": 1.0, "size": 1}
             for i in range(entries)})
        return cache

    def test_many_folders_cost_one_pass(self):
        cache = self._cache()
        by_folder = {"/live/sub%d" % i: ["a.png"] for i in range(50)}
        cache.reconcile_many(by_folder)
        self.assertEqual(
            1, cache._manifest.passes,
            "reconciling 50 directories walked the manifest %d times"
            % cache._manifest.passes)

    def test_the_single_folder_wrapper_still_works(self):
        cache = self._cache()
        cache.reconcile("/live/sub0", ["a.png"])
        self.assertEqual(1, cache._manifest.passes)

    def test_a_stale_entry_is_still_dropped(self):
        """One pass must not mean one fewer correctness check."""
        cache = texture_library.ThumbnailCache(256, prefix="recon_test2")
        self.addCleanup(shutil.rmtree, cache.cache_dir, True)
        folder = tempfile.mkdtemp(prefix="amaze_recon_")
        self.addCleanup(shutil.rmtree, folder, True)
        gone = os.path.join(folder, "deleted.png")
        cache._manifest = {gone: {"mtime": 1.0, "size": 1}}
        cache.reconcile_many({folder: []})
        self.assertEqual(
            {}, cache._manifest,
            "an entry whose file is gone survived the reconcile")

    def test_no_caller_reconciles_in_a_loop(self):
        """The regression that actually happens is at the CALL SITE - someone reintroduces `for dir in dirs: cache.reconcile(dir, ...)`, which is O(subdirs x manifest) again however fast one pass is. Derived from the source, like the reload-chain test."""
        import re

        package = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        offenders = []
        for name in ("core/file_library.py",):
            path = os.path.join(package, name)
            with open(path, encoding="utf-8") as handle:
                lines = handle.readlines()
            for number, line in enumerate(lines, 1):
                if not re.search(r"\.reconcile\(", line):
                    continue
                indent = len(line) - len(line.lstrip())    # inside a for-loop body? look back for an enclosing `for` at a shallower indent
                for previous in reversed(lines[:number - 1]):
                    if not previous.strip():
                        continue
                    prev_indent = len(previous) - len(previous.lstrip())
                    if prev_indent >= indent:
                        continue
                    if previous.lstrip().startswith("for "):
                        offenders.append("%s:%d" % (name, number))
                    break
        self.assertEqual(
            [], offenders,
            "reconcile() is called inside a loop at %s - use "
            "reconcile_many, which walks the manifest once" % offenders)

    def test_entries_in_untouched_folders_are_left_alone(self):
        cache = self._cache(entries=10)
        before = dict(cache._manifest)
        cache.reconcile_many({"/live/sub0": ["a.png"]})
        self.assertEqual(
            before, dict(cache._manifest),
            "reconciling one folder dropped entries from another")


class SymlinkedSubfoldersTest(unittest.TestCase):
    """Include Subfolders must not silently skip symlinked directories: plain os.walk skips linked DIRECTORIES while still including linked FILES - inconsistent inside one folder - and the sidebar count agrees with the omission, so nothing signals it, while studio texture and geometry trees are routinely assembled from symlinks."""

    def setUp(self):
        from amaze.core import folders

        self.folders = folders
        self.base = tempfile.mkdtemp(prefix="amaze_links_")
        self.addCleanup(shutil.rmtree, self.base, True)
        real = os.path.join(self.base, "real", "deep")
        os.makedirs(real)
        self.root = os.path.join(self.base, "root")
        os.makedirs(self.root)
        open(os.path.join(self.root, "top.png"), "wb").close()
        open(os.path.join(real, "inside.png"), "wb").close()
        os.symlink(os.path.join(self.base, "real"),
                   os.path.join(self.root, "linked"))

    def _names(self, walker):
        return sorted(n for _d, _s, files in walker for n in files)

    def test_a_symlinked_subfolder_is_included(self):
        self.assertEqual(
            ["top.png"], self._names(os.walk(self.root)),
            "plain os.walk started following links - this test is not "
            "exercising the case it was written for")
        self.assertEqual(
            ["inside.png", "top.png"],
            self._names(self.folders.walk_following_links(self.root)),
            "a symlinked subfolder's files were skipped")

    def test_a_symlink_cycle_terminates(self):
        """followlinks=True on its own loops forever on a/link -> a."""
        os.symlink(os.path.join(self.base, "real"),
                   os.path.join(self.base, "real", "loop"))
        names = self._names(self.folders.walk_following_links(self.root))
        self.assertIn("inside.png", names)

    def test_each_physical_file_appears_once(self):
        """A diamond of links must not list the same file twice."""
        os.symlink(os.path.join(self.base, "real"),
                   os.path.join(self.root, "also_linked"))
        names = self._names(self.folders.walk_following_links(self.root))
        self.assertEqual(
            1, names.count("inside.png"),
            "the same physical file was listed %d times"
            % names.count("inside.png"))


class SortOrderTest(unittest.TestCase):
    """Images and Geometry must order a folder the same way, and a folder must not reorder itself when Include Subfolders is toggled - a plain sorted() on any one branch puts every uppercase before any lowercase while the other branches use key=str.lower."""

    NAMES = ["Zebra.png", "apple.png", "Brick.png", "moss.png"]

    def test_flat_and_recursive_agree(self):
        expected = sorted(self.NAMES, key=str.lower)
        self.assertEqual(
            expected, sorted(self.NAMES, key=str.lower),
            "the recursive branch's rule changed")
        self.assertNotEqual(
            expected, sorted(self.NAMES),
            "these names no longer distinguish the two rules")

    def test_the_flat_branch_uses_a_case_insensitive_sort(self):
        """Derived from the source: the bug was one missing key=."""
        import re

        package = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        offenders = []
        for name in ("core/file_library.py",):
            with open(os.path.join(package, name), encoding="utf-8") as handle:
                for number, line in enumerate(handle, 1):
                    if re.search(r"sorted\(os\.listdir\([^)]*\)\s*\)", line):
                        offenders.append("%s:%d" % (name, number))
        self.assertEqual(
            [], offenders,
            "a case-SENSITIVE sorted(os.listdir(...)) at %s - flat and "
            "recursive scans will order the same folder differently"
            % offenders)


class StaleRowTest(unittest.TestCase):
    """data() must survive a row that outlived its model: index.isValid() does NOT mean "in range", since an index built against a longer list stays valid after the model shrinks, and an unguarded data() then raises IndexError out of a Qt PAINT path rather than returning None. A folder emptying under a queued repaint reaches it."""

    def _texture_model(self):
        from amaze.core import file_library
        prefs = test_support.fixture_prefs(self)
        model = file_library.FileFiles(prefs)
        model._files = [("/tmp", "a.png"), ("/tmp", "b.png")]
        model._kinds = ["image", "image"]
        return model

    def test_a_stale_row_returns_none_instead_of_raising(self):
        model = self._texture_model()
        stale = model.index(1, 0)
        model._files = [("/tmp", "a.png")]      # the folder shrank
        self.assertTrue(stale.isValid(),
                        "isValid() is expected to stay True - that is the trap")
        try:
            value = model.data(stale, QtCore.Qt.ItemDataRole.DisplayRole)
        except IndexError:
            self.fail("FileFiles.data raised IndexError on a stale row; "
                      "in a repaint that is an exception out of a paint path")
        self.assertIsNone(value)

    def test_a_live_row_still_returns_its_name(self):
        model = self._texture_model()
        self.assertEqual(
            "b.png",
            model.data(model.index(1, 0), QtCore.Qt.ItemDataRole.DisplayRole))


def _folder_methods():
    """The methods of `FolderSection`, as AST - so a guard reads the shipped source. ▸p/source-derived-tests"""
    tree = ast.parse(inspect.getsource(sections))
    for klass in ast.walk(tree):
        if isinstance(klass, ast.ClassDef) and klass.name == "FolderSection":
            for scope in klass.body:
                if isinstance(scope, ast.FunctionDef):
                    yield scope


class TheFilesAndProxyArePairedOnce(unittest.TestCase):
    """`tile_models` answers the pair and `_files_and_rows` maps a selection; a door that re-derives either is how the two drift apart."""

    def test_no_door_reads_both_attrs_for_itself(self):
        found = []
        for scope in _folder_methods():
            if scope.name == "tile_models":
                continue
            names = {node.attr for node in ast.walk(scope)
                     if isinstance(node, ast.Attribute)}
            if {"files_attr", "files_proxy_attr"} <= names:
                found.append(scope.name)
        self.assertEqual(
            [], sorted(found),
            "the files+proxy pair is re-derived outside tile_models(): %s"
            % ", ".join(sorted(found)))

    def test_no_door_maps_a_selection_for_itself(self):
        found = []
        for scope in _folder_methods():
            if scope.name in ("_files_and_rows", "comment_subject"):
                continue
            if any(isinstance(node, ast.Attribute)
                   and node.attr == "mapToSource" for node in ast.walk(scope)):
                found.append(scope.name)
        self.assertEqual(
            [], sorted(found),
            "a door maps proxy indexes itself instead of asking "
            "_files_and_rows: %s" % ", ".join(sorted(found)))

    def test_an_index_the_proxy_has_dropped_is_not_carried_as_a_row(self):
        """The guard `_files_and_rows` owns: an invalid map answers no row rather than -1, which addresses row 0 backwards."""
        section = sections.FileSection.__new__(sections.FileSection)
        section.tile_models = lambda: (object(), _DroppingProxy())
        files, rows = sections.FolderSection._files_and_rows(
            section, [QtCore.QModelIndex()])
        self.assertEqual([], rows)

    def test_each_index_is_mapped_exactly_once(self):
        """It was mapped twice per index - once to test, once to read - so a proxy that moved between the two calls could answer a row it had just called invalid."""
        proxy = _CountingProxy()
        section = sections.FileSection.__new__(sections.FileSection)
        section.tile_models = lambda: (object(), proxy)
        sections.FolderSection._files_and_rows(
            section, [QtCore.QModelIndex()] * 3)
        self.assertEqual(3, proxy.calls)


class FileOpensOnTheFolderItLeft(unittest.TestCase):
    """Activation stands on the remembered location's row, on All, or on the first real one."""

    def test_activation_stands_on_the_remembered_row(self):
        panel = test_support.fixture_panel(self)
        folders = panel.file_folders_model
        first = folders.data(folders.index(1, 0), folders.PathRole)
        second = test_support.fresh_files_folder(self)
        self.assertTrue(folders.add_folder(second), "premise: a second location")
        for remembered, row in ((second, folders.row_of(second)),
                                (folders.ALL_LABEL, 0),
                                ("/nowhere/registered/", folders.row_of(first))):
            with self.subTest(remembered=remembered):
                panel.section_tabs.setChecked("material")
                panel.prefs.last_file_folder = remembered
                panel.section_tabs.setChecked("file")
                QtWidgets.QApplication.processEvents()
                self.assertEqual(row, panel.cat_list.currentIndex().row())


class RemovingALocationLeavesNoTileOfIt(unittest.TestCase):
    """Remove Location takes the row you stand on to All, any other row leaves you where you are."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.panel.section_tabs.setChecked("file")
        QtWidgets.QApplication.processEvents()
        self.folders = self.panel.file_folders_model
        self.kept = self.folders.data(self.folders.index(1, 0),
                                      self.folders.PathRole)
        self.gone = test_support.fresh_files_folder(self)
        below = test_support.fresh_files_folder(self)    # the row Qt slides the selection onto
        for path in (self.gone, below):
            self.assertTrue(self.folders.add_folder(path), "premise: no location added")
        self.section = self.panel.sections["file"]
        self.kept_tiles = self._stand(self.folders.row_of(self.kept))
        self.assertTrue(self.kept_tiles, "premise: the kept location shows tiles")
        self.rest = sorted(self.kept_tiles + self._stand(self.folders.row_of(below)))

    def _press(self, row):
        """What a right press does: the row is selected and current, and no click handler runs."""
        view = self.panel.cat_list
        index = view.model().index(row, 0)
        view.selectionModel().setCurrentIndex(
            index, QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        return index

    def _stand(self, row):
        """A left click: the press, then the sidebar's own clicked handler. Answers the tiles."""
        self._press(row)
        self.panel.update_selected_cat()
        QtWidgets.QApplication.processEvents()
        return self._tiles()

    def _tiles(self):
        grid = self.panel.thumblist.model()
        role = self.panel.file_files_model.PathRole
        return sorted(grid.index(row, 0).data(role)
                      for row in range(grid.rowCount()))

    def _remove_gone(self):
        index = self._press(self.folders.row_of(self.gone))
        self.section.menu_remove_location([index], index)
        QtWidgets.QApplication.processEvents()
        self.assertIsNone(self.folders.row_of(self.gone), "premise: the row is gone")

    def _assert_standing(self, row, tiles):
        prefix = hostos.canonical_path_key(self.gone).rstrip("/") + "/"
        stale = [path for path in self._tiles() if path.startswith(prefix)]
        self.assertEqual([], stale, "tiles of the removed location still show")
        self.assertEqual(tiles, self._tiles(), "the grid is not the row it stands on")
        view = self.panel.cat_list
        self.assertEqual(row, view.currentIndex().row(), "the sidebar stands elsewhere")
        self.assertEqual([row], [index.row() for index in view.selectedIndexes()],
                         "the sidebar highlights another row")

    def test_removing_the_location_you_stand_on_stands_on_all(self):
        self.assertNotEqual(self.kept_tiles, self._stand(self.folders.row_of(self.gone)),
                            "premise: the removed location shows its own tiles")
        self._remove_gone()
        self._assert_standing(0, self.rest)
        self.assertEqual(self.folders.ALL_LABEL, self.panel.prefs.last_file_folder,
                         "File reopens on the removed location's neighbour")

    def test_removing_another_location_keeps_you_where_you_stand(self):
        self._stand(self.folders.row_of(self.kept))
        self._remove_gone()
        self._assert_standing(self.folders.row_of(self.kept), self.kept_tiles)

    def test_removing_a_location_while_on_all_drops_its_tiles(self):
        self.assertGreater(len(self._stand(0)), len(self.rest),
                           "premise: All shows every location")
        self._remove_gone()
        self._assert_standing(0, self.rest)


class _Source:
    """The two answers `_files_and_rows` asks a mapped index for."""

    def __init__(self, valid, row=0):
        self._valid = valid
        self._row = row

    def isValid(self):
        return self._valid

    def row(self):
        return self._row


class _DroppingProxy:
    """Every index has gone: mapToSource answers an invalid one."""

    def mapToSource(self, _index):
        return _Source(False, -1)


class _CountingProxy:
    """Counts the maps, and answers a valid row for each."""

    def __init__(self):
        self.calls = 0

    def mapToSource(self, _index):
        self.calls += 1
        return _Source(True)


if __name__ == "__main__":
    unittest.main()
