"""The thumbnail engine must not be garbage collected mid-flight.

Reopening the panel RELOADS core/thumbnails, which re-runs the module
body and replaces the `engine` singleton. The old engine held the only
references to its running loader threads, so the collector freed a
QThread whose run() was still executing - a dealloc inside the running
thread, which takes the process down rather than raising something
catchable. The log recorded its milder cousin as
"Internal C++ object (_FileLoader) already deleted".

These tests drive that exact sequence.
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
    """Real image files - the loader must have genuine work to do, or
    the thread finishes before the reload and proves nothing."""
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
        """The panel-reopen sequence, end to end."""
        self._queue(thumbnails.engine, "reload")
        before = thumbnails.engine
        running = [t for t in before._threads if t.isRunning()]
        self.assertTrue(running, "no loader was running - test is vacuous")

        importlib.reload(thumbnails)
        self.assertIsNot(thumbnails.engine, before,
                         "reload did not replace the singleton")
        # The handover must have stopped the old engine's threads BEFORE
        # the collector can reach them.
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
        """_prune_threads walks thread objects; one whose C++ side is
        already gone must be dropped, not raise."""
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
    """One loader finishing must not condemn a sibling's deliveries.

    _prune_threads marks any still-"pending" key of a FINISHED loader as
    "missing", on the sound reasoning that a loader's deliveries are
    queued before its own finished signal. That guarantee is PER-THREAD,
    and the method used to judge every thread it found finished - so a
    sibling that had just finished, with its `loaded` signals still
    sitting unhandled in the main thread's queue, had its keys condemned
    by someone else's prune. _on_loaded then dropped the real images,
    because the state was no longer "pending".

    Sticky, too: texture_library short-circuits on is_missing(), so
    those rows never even fall back to the disk cache on a revisit.

    Measured over 300 real PNGs, keys never reaching "done", with a 3ms
    repaint handler standing in for the model:

        parallel=4, idle main thread   HEAD 0,0,0,0      fix 0,0,0,0
        parallel=4, 3ms repaints       HEAD 3,2,15,5     fix 0,0,0,0
        parallel=8, idle main thread   HEAD 2,1,3,1      fix 0,0,0,0
        parallel=8, 3ms repaints       HEAD 27,29,52,22  fix 0,0,0,0

    Zero loss with an idle main thread at the default parallelism, which
    is why this read as intermittent rather than as a bug."""

    class _FinishedLoader:
        """A loader that has finished but whose deliveries have not been
        handled yet - the state the race turns on."""

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
        """Cancelled work is unrequested, not missing: the revisit
        re-queues it."""
        self.first._canceled = True
        self.engine._prune_threads(self.first)
        self.assertEqual("pending", self.engine._states["a1"])


class TestConvertCancellation(unittest.TestCase):
    """A worker inside a long iconvert must let go when asked.

    `conversion._run_process` has always taken a `cancelled` callback
    and polled it every 100ms from inside its nested event loop - and no
    caller ever passed one, so the whole watchdog was dead code. cancel()
    could
    therefore only take effect BETWEEN items; a worker already inside a
    30s iconvert ignored it.

    That is what made shutdown() fall through to wait(3000) and then
    terminate(). Measured with a fake iconvert that sleeps 25s:

        at HEAD : shutdown 3.01s, iconvert child orphaned and still alive
        wired   : shutdown 0.09s, no orphan, terminate() never reached

    With Parallel Conversions at 8 those 3s are sequential, so a panel
    reopen could stall ~24s and leave 8 orphaned Houdini subprocesses.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="amaze_cancel_")
        self.addCleanup(shutil.rmtree, self.tmp, True)

        # A stand-in for Houdini's iconvert that simply takes far longer
        # than the test is willing to wait.
        binary = os.path.join(self.tmp, "hfs", "bin")
        os.makedirs(binary)
        self.hfs = os.path.dirname(binary)
        script = os.path.join(binary, "iconvert")
        with open(script, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/bash\nsleep 25\n")
        os.chmod(script, 0o755)

        self.source = os.path.join(self.tmp, "in.exr")
        with open(self.source, "wb") as handle:
            handle.write(b"\x76\x2f\x31\x01" + b"\0" * 400)

    def _children(self):
        result = subprocess.run(
            ["pgrep", "-P", str(os.getpid())],
            capture_output=True, text=True)
        return result.stdout.split()

    @unittest.skipUnless(sys.platform != "win32",
                         "the probe uses a bash stub and pgrep")
    def test_shutdown_does_not_wait_out_a_running_iconvert(self):
        engine = thumbnails.ThumbnailEngine()
        loader = thumbnails._ConvertLoader(
            [("k%d" % i, self.source, 256) for i in range(3)], self.hfs)
        engine._threads.append(loader)
        self.addCleanup(loader.wait, 5000)
        loader.start()

        # Wait until it is genuinely INSIDE the subprocess, otherwise
        # this measures nothing.
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
    def test_a_cancelled_worker_kills_its_own_subprocess(self):
        """terminate() skipped the cleanup, orphaning a real Houdini
        subprocess for every stuck worker."""
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
        self.assertTrue(self._children())

        engine.shutdown()
        # The kill is issued by the worker as it unwinds; give it a beat.
        deadline = time.time() + 3
        while time.time() < deadline and self._children():
            _app.processEvents()
            time.sleep(0.05)

        self.assertEqual(
            [], self._children(),
            "the iconvert child outlived the panel that started it")


class TestParkedThreadsSurviveReload(unittest.TestCase):
    """The parking lot must not be emptied by a panel reopen.

    thumbnails._unstoppable holds the last Python reference to QThreads
    that refused to stop. panel.py reloads this module on every panel
    open, and reload re-runs the module body - so a plain `= []` handed
    the collector every thread parked by an earlier reopen.

    The crash is DEFERRED, which is why this read as harmless: nothing
    dies at reload time. A running PySide QThread is kept alive by the
    bound `self.run` method held by C++ QThreadWrapper::run(), and the
    dying thread releases that reference ITSELF when run() returns - so
    the parked reference is the one that must exist at COMPLETION.
    Measured with a real loader parked by a real shutdown():

        QThread: Destroyed while thread is still running
        QMessageLogger::fatal -> abort()   (inside QThreadWrapper::run)
    """

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
        """The parking lot survives; the ENGINE must not. The reload
        exists so code edits take effect on reopen."""
        before = thumbnails.engine
        importlib.reload(thumbnails)
        self.assertIsNot(
            thumbnails.engine, before,
            "the reload stopped replacing the engine - edits to "
            "ThumbnailEngine would no longer take effect on a reopen")


class TestDeliveriesSurviveAReload(unittest.TestCase):
    """Two Amaze pane tabs is a supported layout, and opening the second
    used to kill the first one's thumbnails.

    Models connect at CONSTRUCTION, but the engine SINGLETON is replaced
    on every module reload and the handover shuts the old one down. So
    the first tab's models stayed wired to a dead engine.

    Measured: after the reload the new engine loaded and cached all 6
    loadable rows and a later data() call returned 7/7 images, but 0 of
    7 arrival repaints reached the old model - so its tiles sat on
    placeholders while idle and filled in only on the next scroll or
    resize, and its texture progress bar froze."""

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
    """A 0ms re-arm runs the dispatcher on EVERY event-loop turn while
    it waits for a slot - and a convert slot is an iconvert that can
    run 30s. _dispatch_files hit the identical shape and measured
    ~7.5s of pure spin before moving to 16ms; _dispatch_converts was
    the sibling the fix never reached."""

    def test_no_dispatcher_rearms_at_zero_delay(self):
        """Scoped to the `_dispatch_*` bodies: the 0ms one-shots that
        ARM a dispatcher from the request path, or hand a result back,
        fire once and are fine - the spin is a dispatcher re-arming
        ITSELF at 0."""
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
