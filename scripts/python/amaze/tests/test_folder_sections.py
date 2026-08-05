"""
The File section's folder browsing and its disk caches.

Images and Geometry were twin sections on one ThumbnailCache until the
2026-07-31 merge folded them (with HIP) into the File section - one
model, per-kind pipelines, still the same shared cache class. The bugs
pinned here were all of the twin shape: a fix applied to one pipeline
and not the other, which is exactly what the merge exists to end.
"""

import os
import shutil
import sys
import tempfile
import unittest

# THREE dirnames up = scripts/python, the directory holding the
# `amaze` package - the DEV tree, not the install on Houdini's path.
sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401
from amaze.core import texture_library, thumbnails  # noqa: E402
from amaze.tests import test_support  # noqa: E402


class DeleteLocalCacheTest(unittest.TestCase):
    """"Delete Local Cache" must not break Geometry for the session.

    ThumbnailCache.clear() sweeps every texture_thumbnails_* AND
    geo_thumbnails_* directory - correct, they would pile up otherwise -
    but recreates only its OWN. GeoFiles._get_cache() memoises its cache
    on (size, mode, bg), none of which change when the cache is cleared,
    so it kept handing back an object whose directory no longer existed.

    Measured before the fix: after one press, the geometry render's
    _render_tmp.png could not be written, put() cached nothing, and it
    repeated on every folder visit until Houdini restarted. Only a
    print() reported it."""

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
        """GeoFiles renders to _render_tmp.png inside the cache dir
        BEFORE the cache is asked to store anything."""
        self.textures.clear()
        self.geometry.ensure_dir()
        scratch = os.path.join(self.geometry.cache_dir, "_render_tmp.png")
        self.assertTrue(
            self.image.save(scratch, "PNG"),
            "the geometry render could not write its scratch file")

    def test_a_failed_write_is_not_recorded_as_cached(self):
        """QImage.save returns False rather than raising, so a write into
        a missing directory used to fall through to the manifest and
        record a cache entry for a file that was never written -
        valid_path then found nothing and it re-rendered forever."""
        shutil.rmtree(self.geometry.cache_dir, ignore_errors=True)
        # Block recreation so the write genuinely fails.
        open(self.geometry.cache_dir, "w").close()
        self.addCleanup(os.remove, self.geometry.cache_dir)

        self.geometry.put(self.source, self.image)
        self.assertEqual(
            {}, self.geometry._manifest,
            "the manifest recorded a thumbnail that was never written")


class CacheIsolationTest(unittest.TestCase):
    """The tests above call clear(), which SWEEPS the cache root.

    Against the default root that deletes the user's real texture and
    geometry thumbnails - which happened once, while writing this file.
    Regenerable, but geometry thumbnails are Karma renders. test_support
    redirects the root at import; this is the tripwire."""

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
    """The conversion bar must be able to reach 100%.

    _progress_total counted ROWS while _on_convert_attempted discards by
    KEY, and _progress_keys deduplicates. Two rows can share a canonical
    path - overlapping registered folders with Include Subfolders on
    (/root and /root/sub), or a case-variant duplicate on a
    case-insensitive volume - so the bar stopped short forever.

    Worse than a cosmetic stall: the `_progress_done >= _progress_total`
    gate is what flushes the manifest, so nothing was ever recorded and
    the whole folder re-converted from scratch on every visit."""

    def setUp(self):
        # /root and /root/sub BOTH registered, recursion on: the same
        # physical file is reached twice, which is the whole case.
        self.root = tempfile.mkdtemp(prefix="amaze_overlap_")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.sub = os.path.join(self.root, "sub")
        os.makedirs(self.sub)
        # An EXR: not natively decodable, so it takes the convert path
        # and is counted, rather than being served from cache.
        with open(os.path.join(self.sub, "tex.exr"), "wb") as handle:
            handle.write(b"\x76\x2f\x31\x01" + b"\0" * 256)

        self.prefs = test_support.fixture_prefs(self)
        # Through the setter: `file_recursive_folders` is derived from
        # the library's location store now, so extending the list it
        # returns changes a value nothing will ever read again.
        for folder in (self.root, self.sub):
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
        """The consequence, not the counter: every key reports once, so
        done must be able to reach total."""
        self.model._load([self.root, self.sub])
        for key in list(self.model._progress_keys):
            self.model._on_convert_attempted(key)
        self.assertGreaterEqual(
            self.model._progress_done, self.model._progress_total,
            "the conversion pass finished but the bar never completed, "
            "so the manifest was never flushed and this folder will "
            "re-convert from scratch on every visit")


class ReconcileIsOnePassTest(unittest.TestCase):
    """Opening a folder must not walk the manifest once per subfolder.

    reconcile() walks the whole manifest, and the callers called it once
    per containing directory - so Include Subfolders made a folder open
    O(subdirs x manifest). The manifest is global per resolution and
    grows with every file ever thumbnailed, so it degraded
    monotonically. Measured, 300 subdirs against a 40,000-entry
    manifest: 3.37s of pure dict iteration on the main thread, against
    0.01s for a single pass.

    Counted rather than timed: a timing assertion here would be flaky,
    and the invariant is "one pass", not "fast"."""

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
        """The regression that actually happens is at the CALL SITE:
        someone reintroduces `for dir in dirs: cache.reconcile(dir, ...)`,
        which is O(subdirs x manifest) again however fast one pass is.
        Derived from the source, like the reload-chain test."""
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
                # Inside a for-loop body? Look back for an enclosing
                # `for` at a shallower indent.
                indent = len(line) - len(line.lstrip())
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
    """Include Subfolders must not silently skip symlinked directories.

    Plain os.walk skips linked DIRECTORIES while still including linked
    FILES - inconsistent inside one folder - and the sidebar count
    agrees with the omission, so nothing signals it. Studio texture and
    geometry trees are routinely assembled from symlinks."""

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
    """Images and Geometry must order a folder the same way, and a
    folder must not reorder itself when Include Subfolders is toggled.

    Images' flat branch used plain sorted() (ASCII: every uppercase
    before any lowercase) while its own recursive branch and BOTH
    geometry branches used key=str.lower."""

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
    """data() must survive a row that outlived its model.

    index.isValid() does NOT mean "in range" - an index built against a
    longer list stays valid after the model shrinks. GeoFiles.data has
    always guarded; TextureFiles.data did not, so the same stale row
    raised IndexError out of a Qt PAINT path rather than returning None.
    A folder emptying under a queued repaint reaches it."""

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


if __name__ == "__main__":
    unittest.main()
