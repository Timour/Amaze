"""The thumbnail engine must not be collected mid-flight. Reopening the panel RELOADS this module and replaces the `engine` singleton, so anything holding the last reference to a running QThread frees it inside its own `run()` - which takes the process down rather than raising. ▸archive/test_thumbnail_shutdown.py
"""

import gc
import glob
import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import thumbnails  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401 - import redirects the debug log


def _sample_images(count=40):
    """Real image files - without genuine work the thread finishes before the reload and proves nothing."""
    from amaze.prefs import prefs as prefs_mod
    library = prefs_mod.Prefs()
    library.load()
    found = glob.glob(os.path.join(library.dir, library.img_dir, "*.png"))
    if len(found) < 4:
        here = os.path.dirname(os.path.abspath(__file__))
        found = glob.glob(os.path.join(here, "assets", "**", "*.png"),
                          recursive=True)
    return found[:count]


class TestThumbnailShutdown(unittest.TestCase):

    def setUp(self):
        self.images = _sample_images()
        if len(self.images) < 4:
            self.skipTest("no sample images available")

    def _queue(self, engine, tag):
        for i, path in enumerate(self.images):
            engine.request_file((tag, i), path)
        _app.processEvents()

    def test_shutdown_stops_running_loaders(self):
        engine = thumbnails.ThumbnailEngine()
        self._queue(engine, "shutdown")
        engine.shutdown()
        self.assertEqual(engine._threads, [])
        # Idempotent - a second call must not raise.
        engine.shutdown()

    def test_module_reload_does_not_orphan_running_threads(self):
        """The panel-reopen sequence end to end - the handover must stop the old engine's threads BEFORE the collector can reach them."""
        self._queue(thumbnails.engine, "reload")
        before = thumbnails.engine
        running = [t for t in before._threads if t.isRunning()]
        self.assertTrue(running, "no loader was running - test is vacuous")

        importlib.reload(thumbnails)
        self.assertIsNot(thumbnails.engine, before,
                         "reload did not replace the singleton")
        self.assertEqual(before._threads, [],
                         "old engine kept threads after the reload")
        for thread in running:
            self.assertFalse(thread.isRunning(),
                             "a loader survived the handover still running")

        del before
        gc.collect()
        for _ in range(20):
            _app.processEvents()
            time.sleep(0.01)

    def test_prune_survives_a_deleted_thread(self):
        """A thread whose C++ side is already gone must be dropped, never raise."""
        engine = thumbnails.ThumbnailEngine()

        class _Gone:
            def isFinished(self):
                raise RuntimeError("Internal C++ object already deleted.")

            def keys(self):
                raise RuntimeError("Internal C++ object already deleted.")

        engine._threads = [_Gone()]
        engine._prune_threads()          # must not raise
        self.assertEqual(engine._threads, [])


class TestPruneJudgesOnlyItsOwnLoader(unittest.TestCase):
    """A loader may condemn only its OWN pending keys - the deliveries-before-finished guarantee is PER-THREAD, so judging a sibling drops real images whose signals are still queued, and it sticks because a missing key never falls back to the disk cache."""

    class _FinishedLoader:
        """Finished, but with its deliveries not yet handled - the state the race turns on."""

        def __init__(self, keys):
            self._keys = list(keys)
            self._canceled = False

        def keys(self):
            return self._keys

        def isFinished(self):
            return True

    def setUp(self):
        self.engine = thumbnails.ThumbnailEngine()
        self.first = self._FinishedLoader(["a1"])
        self.second = self._FinishedLoader(["b1"])
        self.engine._threads = [self.first, self.second]
        self.engine._states = {"a1": "pending", "b1": "pending"}

    def test_a_siblings_keys_are_left_alone(self):
        self.engine._prune_threads(self.first)
        self.assertEqual("missing", self.engine._states["a1"],
                         "the finisher's own undelivered key must be judged")
        self.assertEqual(
            "pending", self.engine._states["b1"],
            "a sibling loader's key was condemned by someone else's "
            "prune; its real image is dropped when it arrives")

    def test_the_siblings_image_still_lands(self):
        """The behaviour, end to end: prune, then the queued delivery."""
        self.engine._prune_threads(self.first)
        image = QtGui.QImage(4, 4, QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtGui.QColor("red"))
        self.engine._on_loaded("b1", image)
        self.assertEqual(
            "done", self.engine._states["b1"],
            "the sibling's image was dropped - that tile stays blank for "
            "the rest of the session")

    def test_the_finisher_is_dropped_from_the_thread_list(self):
        self.engine._prune_threads(self.first)
        self.assertNotIn(self.first, self.engine._threads)
        self.assertIn(
            self.second, self.engine._threads,
            "a finished sibling must stay referenced until its own "
            "finished signal - Qt may still hold queued deliveries from it")

    def test_a_cancelled_loader_marks_nothing_missing(self):
        """Cancelled work is unrequested, not missing - the revisit re-queues it."""
        self.first._canceled = True
        self.engine._prune_threads(self.first)
        self.assertEqual("pending", self.engine._states["a1"])


class TestConvertCancellation(unittest.TestCase):
    """A worker inside a long iconvert must let go when asked. The `cancelled` callback has to be PASSED - unwired, cancel only takes effect between items, so shutdown waits out the process and then terminates it, orphaning a Houdini subprocess per stuck worker."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="amaze_cancel_")
        self.addCleanup(shutil.rmtree, self.tmp, True)

        # Stands in for iconvert, taking longer than the test will wait.
        binary = os.path.join(self.tmp, "hfs", "bin")
        os.makedirs(binary)
        self.hfs = os.path.dirname(binary)
        self.script = os.path.join(binary, "iconvert")
        with open(self.script, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/bash\nsleep 25\n")
        os.chmod(self.script, 0o755)

        self.source = os.path.join(self.tmp, "in.exr")
        with open(self.source, "wb") as handle:
            handle.write(b"\x76\x2f\x31\x01" + b"\0" * 400)

    def _children(self):
        """The pids running THIS test's fake iconvert - `pgrep -P` alone asks only whether there is A child, which another module's leftover satisfies, and that is a false green."""
        found = subprocess.run(
            ["pgrep", "-P", str(os.getpid())],
            capture_output=True, text=True)
        mine = []
        for pid in found.stdout.split():
            described = subprocess.run(
                ["ps", "-o", "command=", "-p", pid],
                capture_output=True, text=True)
            if self.script in described.stdout:
                mine.append(pid)
        return mine

    @unittest.skipUnless(sys.platform != "win32",
                         "the probe uses a bash stub and pgrep")
    def test_shutdown_does_not_wait_out_a_running_iconvert(self):
        engine = thumbnails.ThumbnailEngine()
        loader = thumbnails._ConvertLoader(
            [("k%d" % i, self.source, 256) for i in range(3)], self.hfs)
        engine._threads.append(loader)
        self.addCleanup(loader.wait, 5000)
        loader.start()

        # Wait until it is genuinely INSIDE the subprocess, or this measures nothing.
        deadline = time.time() + 10
        while time.time() < deadline and not self._children():
            _app.processEvents()
            time.sleep(0.05)
        self.assertTrue(self._children(),
                        "the worker never reached the subprocess")

        start = time.time()
        engine.shutdown()
        elapsed = time.time() - start

        self.assertLess(
            elapsed, 2.0,
            "shutdown waited out the full wait(3000) - the cancelled "
            "callback is not reaching _run_process, so cancel() cannot "
            "interrupt a running iconvert (measured 3.01s at HEAD)")
        self.assertEqual(
            [], thumbnails._unstoppable,
            "a worker had to be parked, so terminate() was reached")

    @unittest.skipUnless(sys.platform != "win32",
                         "the probe uses a bash stub and pgrep")
    def test_an_unrelated_child_does_not_count_as_the_subprocess(self):
        other = subprocess.Popen(["sleep", "5"])
        self.addCleanup(other.wait)
        self.addCleanup(other.terminate)
        self.assertEqual(
            [], self._children(),
            "a child that is not this test's fake iconvert was counted, "
            "so the wait for the subprocess can be satisfied by any "
            "process at all - the setup would pass without ever starting "
            "the thing these tests guard")

    @unittest.skipUnless(sys.platform != "win32",
                         "the probe uses a bash stub and pgrep")
    def test_a_cancelled_worker_kills_its_own_subprocess(self):
        """`terminate()` skips the cleanup, orphaning a real Houdini subprocess for every stuck worker."""
        engine = thumbnails.ThumbnailEngine()
        loader = thumbnails._ConvertLoader(
            [("k0", self.source, 256)], self.hfs)
        engine._threads.append(loader)
        self.addCleanup(loader.wait, 5000)
        loader.start()

        deadline = time.time() + 10
        while time.time() < deadline and not self._children():
            _app.processEvents()
            time.sleep(0.05)
        self.assertTrue(
            self._children(),
            "SETUP, NOT THE GUARDED BUG: no fake iconvert appeared within "
            "10s, so this never reached the orphan check at all. Either "
            "the worker was slow to spawn under load, or it answered "
            "without shelling out. Do not read this as the orphan "
            "regression - the two failures are not the same event.")

        engine.shutdown()
        deadline = time.time() + 3
        while time.time() < deadline and self._children():
            _app.processEvents()
            time.sleep(0.05)

        self.assertEqual(
            [], self._children(),
            "the iconvert child outlived the panel that started it")


class TestParkedThreadsSurviveReload(unittest.TestCase):
    """`_unstoppable` holds the last reference to threads that refused to stop, so a plain `= []` on reload hands them to the collector. The crash is DEFERRED to when each thread COMPLETES, which is why an empty parking lot reads as harmless."""

    def test_a_reload_keeps_the_parked_threads(self):
        marker = object()
        thumbnails._unstoppable.append(marker)
        before = thumbnails._unstoppable
        self.addCleanup(
            lambda: marker in thumbnails._unstoppable
            and thumbnails._unstoppable.remove(marker))
        try:
            importlib.reload(thumbnails)
            self.assertIs(
                before, thumbnails._unstoppable,
                "the reload replaced the parking lot - every thread parked "
                "by an earlier panel open just lost its last reference")
            self.assertIn(
                marker, thumbnails._unstoppable,
                "a parked thread did not survive a panel reopen")
        finally:
            if marker in thumbnails._unstoppable:
                thumbnails._unstoppable.remove(marker)

    def test_the_engine_is_still_replaced_by_a_reload(self):
        """The parking lot survives, the ENGINE must not - the reload exists so code edits take effect on reopen."""
        before = thumbnails.engine
        importlib.reload(thumbnails)
        self.assertIsNot(
            thumbnails.engine, before,
            "the reload stopped replacing the engine - edits to "
            "ThumbnailEngine would no longer take effect on a reopen")


class TestDeliveriesSurviveAReload(unittest.TestCase):
    """Two pane tabs is a supported layout. Models connect at CONSTRUCTION and the engine singleton is replaced on every reload, so an existing tab is left wired to a dead engine - its tiles sit on placeholders until the next scroll."""

    def test_a_model_still_hears_the_engine_after_a_reload(self):
        from amaze.core import library as library_mod

        prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        model = library_mod.MaterialLibrary(preferences=prefs)
        if not model.rowCount():
            self.skipTest("fixture library is empty")

        hits = []
        model.dataChanged.connect(lambda *a: hits.append(1))
        key = model._thumb_key(0)
        model._states = {}

        before = thumbnails.engine
        importlib.reload(thumbnails)
        self.assertIsNot(
            thumbnails.engine, before,
            "the reload stopped replacing the engine - this test is not "
            "exercising the case it was written for")

        hits.clear()
        thumbnails.engine.ready.emit(key)
        self.assertEqual(
            1, len(hits),
            "a delivery from the NEW engine never reached a model built "
            "before the reload")

    def test_the_relay_itself_survives_the_reload(self):
        before = thumbnails.signals
        importlib.reload(thumbnails)
        self.assertIs(
            before, thumbnails.signals,
            "the relay was rebuilt, which drops every model connected "
            "through it")


class DispatchWaitsAFrameNotATurn(unittest.TestCase):
    """A 0ms re-arm runs the dispatcher on EVERY event-loop turn while it waits for a slot, and a convert slot can be a 30s iconvert."""

    def test_no_dispatcher_rearms_at_zero_delay(self):
        """Scoped to the `_dispatch_*` bodies - a 0ms one-shot that ARMS a dispatcher fires once and is fine; the spin is a dispatcher re-arming ITSELF."""
        import ast

        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "core", "thumbnails.py")
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        offenders = []
        dispatchers = 0
        for func in ast.walk(tree):
            if not (isinstance(func, ast.FunctionDef)
                    and func.name.startswith("_dispatch_")):
                continue
            dispatchers += 1
            offenders.extend(
                node.lineno
                for node in ast.walk(func)
                if isinstance(node, ast.Call)
                and getattr(node.func, "attr", "") == "singleShot"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == 0)
        self.assertGreaterEqual(dispatchers, 2,
                                "the dispatchers were not found - the "
                                "scan is vacuous")
        self.assertEqual(
            [], offenders,
            "a dispatcher re-arms itself at 0ms - a busy-poll of the "
            "UI thread for the life of the queue: lines %s" % offenders)


if __name__ == "__main__":
    unittest.main()
