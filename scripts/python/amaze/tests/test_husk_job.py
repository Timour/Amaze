"""One background husk per batch: command, per-frame swap, progress, Cancel. ▸r/husk-startup"""

import os
import shutil
import sys
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze import preview  # noqa: E402
from amaze.core import tile_icons  # noqa: E402
from amaze.render import husk_job, thumbs  # noqa: E402
from amaze.tests import test_support  # noqa: E402

OCIO = {"display": hou.Color.ocio_defaultDisplay(), "view": hou.Color.ocio_defaultView(),
        "space": "scene_linear"}
RED, GREEN = (0.8, 0.05, 0.05), (0.05, 0.8, 0.05)
PLASTIC = "139888337459841200"    # a fixture whose surface takes its colour from a parm
OCTANE_SHADER = "octane::NT_MAT_STANDARD_SURFACE"


def _patch_viewer(testcase):
    """Headless there is no Scene Viewer: both seams that read one answer this OCIO."""
    for target in (preview.thumbnail_scene, preview):
        patcher = mock.patch.object(target, "ocio_from_viewer", lambda: dict(OCIO))
        patcher.start()
        testcase.addCleanup(patcher.stop)


def _plastic(testcase, colour):
    """The plastic fixture in a plain holder, its base colour set."""
    holder = hou.node("/mat").createNode("subnet")
    testcase.addCleanup(test_support.drop_node, holder)
    holder.loadItemsFromFile(os.path.join(test_support.FIXTURE_DIR, "mat", PLASTIC + ".mat"))
    surface = next(c for c in holder.children() if c.type().name() == "mtlxstandard_surface")
    surface.parmTuple("base_color").set(colour)
    return holder


def _octane(testcase, colour):
    import octane_material_builder
    builder = octane_material_builder.createMaskedOctaneSubnet(target_node=hou.node("/mat"))
    testcase.addCleanup(test_support.drop_node, builder)
    shader = next(c for c in builder.children() if c.type().name() == OCTANE_SHADER)
    shader.parmTuple("baseColor").set(colour)
    return builder


def _hue(png):
    """`red`, `green` or `neither`, from the middle third of the picture."""
    img = QtGui.QImage(png)
    if img.isNull():
        return "no picture"
    w, h = img.width(), img.height()
    r = g = b = n = 0
    for y in range(h // 3, 2 * h // 3):
        for x in range(w // 3, 2 * w // 3):
            c = img.pixelColor(x, y)
            r, g, b, n = r + c.red(), g + c.green(), b + c.blue(), n + 1
    r, g, b = r / n, g / n, b / n
    if r > g + 15 and r > b + 15:
        return "red"
    if g > r + 15 and g > b + 15:
        return "green"
    return "neither (%d, %d, %d)" % (r, g, b)


class TheCommandAndItsEnvironment(unittest.TestCase):

    def _job(self, renderer, count=3):
        batch = {"usd": "/x/__render__.usd", "prims": ["/m%d" % i for i in range(count)],
                 "ball": "/ball", "renderer": renderer, "ocio": ("d", "v", "s")}
        return husk_job.HuskJob(batch, "/x", [("id%d" % i, "/p%d.png" % i)
                                              for i in range(count)])

    def test_each_husk_skips_the_other_renderers_plugins(self):
        """Octane aborts without its own plugin; a pattern already set is kept, a braced one wins."""
        for renderer, current, expected in (
                ("Karma", "", "{redshift4houdini.*,Houdini_Octane*}"),
                ("Octane", "", "redshift4houdini.*"),
                ("Octane", "mine*", "{mine*,redshift4houdini.*}"),
                ("Karma", "{a,b}", "{a,b}")):
            with self.subTest(renderer=renderer, current=current):
                self.assertEqual(expected,
                                 husk_job.plugin_exclusion(renderer, current))

    def test_the_environment_carries_the_exclusion(self):
        with mock.patch.dict(os.environ, {husk_job.EXCLUDE: ""}):
            env = self._job("Karma").environment()
        self.assertEqual(husk_job.plugin_exclusion("Karma"), env[husk_job.EXCLUDE])

    def test_one_husk_renders_every_frame_and_only_octane_restarts(self):
        """Octane keeps frame 1's material unless restarted ▸r/husk-startup."""
        cmd = self._job("Karma", 3).command()
        self.assertEqual(["-f", "1", "-n", "3"], cmd[cmd.index("-f"):cmd.index("-f") + 4])
        self.assertIn("1a", cmd[cmd.index("-V") + 1])    # `a` prints ALF_PROGRESS
        self.assertTrue(cmd[cmd.index("-o") + 1].endswith("frame.$F4.exr"))
        self.assertIn("--preframe-script", cmd)
        self.assertIn("--postframe-script", cmd)
        self.assertEqual("/x/__render__.usd", cmd[-1])
        self.assertNotIn("--restart-delegate", cmd)
        octane = self._job("Octane").command()
        self.assertEqual("1", octane[octane.index("--restart-delegate") + 1])

    def test_a_script_path_with_a_space_is_quoted(self):
        self.assertEqual('"/a b/p.py"', husk_job._script_arg("/a b/p.py"))
        self.assertEqual("/ab/p.py", husk_job._script_arg("/ab/p.py"))


class ARenderIsJudgedByItsFrames(unittest.TestCase):
    """22.0.482's husk exits 139 after its last frame ▸r/husk-startup; a stand-in husk plays it."""

    def _run(self, reported):
        """A three-frame job whose stand-in husk reports `reported` frames done, then exits 139."""
        job = husk_job.HuskJob({"usd": "", "prims": [], "ball": "", "renderer": "Karma"},
                               test_support.scratch_dir("amaze_husk_job_"),
                               [("id%d" % n, "") for n in range(3)])
        self.addCleanup(job.discard)
        husk = [test_support.plain_python(), "-c",
                "import sys\nfor n in range(1, %d):\n    print('%s %%d' %% n, flush=True)\n"
                "sys.exit(139)\n" % (reported + 1, husk_job.DONE)]
        with mock.patch.object(job, "command", lambda: husk), test_support.captured_log() as log:
            job.run_blocking()
        return job, log

    def test_an_exit_after_every_frame_is_done(self):
        job, log = self._run(3)
        self.assertEqual("done", job.status)
        self.assertEqual([], log.matching("render stopped"), "a finished render said it stopped")
        finished = [(r["data"].get("status"), r["data"].get("code"))
                    for r in log.records("thumb") if r["msg"] == "husk finished"]
        self.assertEqual([("done", 139)], finished, "the log lost husk's exit code")

    def test_an_exit_before_the_last_frame_is_a_failure(self):
        job, log = self._run(2)
        self.assertEqual("failed: husk exit 139", job.status)
        self.assertEqual(1, len(log.matching("render stopped (husk exit 139)")),
                         "a render missing a frame did not say so")


class AFrameWithNoPictureIsRecorded(unittest.TestCase):
    """A frame husk calls done with no EXR, or one that converts to nothing, is in the log."""

    def _run(self, write_exr):
        """A two-frame job whose stand-in husk reports both done, writing frame 1's EXR or not."""
        folder = test_support.scratch_dir("amaze_husk_frames_")
        self.addCleanup(shutil.rmtree, folder, True)
        job = husk_job.HuskJob({"usd": "", "prims": [], "ball": "", "renderer": "Karma",
                                "ocio": ("d", "v", "s")}, folder,
                               [("NO_EXR_%d" % n, os.path.join(folder, "p%d.png" % n))
                                for n in (1, 2)])
        exr = os.path.join(folder, "f1.exr") if write_exr else ""
        husk = [test_support.plain_python(), "-c",
                "import sys\nif %r:\n    open(%r, 'wb').write(b'x')\n"
                "print('%s 1', flush=True)\nprint('%s 2', flush=True)\n"
                % (bool(exr), exr, husk_job.DONE, husk_job.DONE)]
        written = []
        slot = written.append
        husk_job.jobs.thumbnailWritten.connect(slot)
        self.addCleanup(husk_job.jobs.thumbnailWritten.disconnect, slot)
        with mock.patch.object(job, "command", lambda: husk), \
                mock.patch.object(preview, "exr_to_png", return_value=False), \
                test_support.captured_log() as log:
            husk_job.jobs.submit(job, blocking=True)
        self.assertEqual([], written, "a tile was told a picture landed")
        return [(r["data"].get("asset_id"), r["data"].get("frame"))
                for r in log.records("thumb") if r["data"].get("frame") is not None]

    def test_a_missing_exr_is_logged_per_frame(self):
        self.assertEqual([("NO_EXR_1", 1), ("NO_EXR_2", 2)], self._run(write_exr=False))

    def test_an_exr_that_converts_to_nothing_is_logged(self):
        self.assertEqual([("NO_EXR_1", 1), ("NO_EXR_2", 2)], self._run(write_exr=True))


class QuittingLeavesNoJobFolder(unittest.TestCase):
    """At Houdini's exit the running husk stops and every job's folder goes with it."""

    def _sleeper(self, jobs):
        folder = test_support.scratch_dir("amaze_husk_quit_")
        self.addCleanup(shutil.rmtree, folder, True)
        job = husk_job.HuskJob({"usd": "", "prims": [], "ball": "", "renderer": "Karma"},
                               folder, [("QUIT", "")])
        husk = [test_support.plain_python(), "-c", "import time\ntime.sleep(60)\n"]
        patcher = mock.patch.object(job, "command", lambda: husk)
        patcher.start()
        self.addCleanup(patcher.stop)
        jobs.submit(job)
        return job

    def test_stop_now_discards_the_running_and_the_waiting(self):
        jobs = husk_job.Jobs()
        running, waiting = self._sleeper(jobs), self._sleeper(jobs)
        self.addCleanup(lambda: running._proc and running._proc.kill())
        self.addCleanup(lambda: running._timer and running._timer.stop())
        self.assertIs(running, jobs._running, "premise: the first job is not the running one")
        self.assertTrue(os.path.isdir(waiting.job_dir), "premise: no waiting folder")
        jobs.stop_now()
        self.assertFalse(os.path.exists(running.job_dir), "the running job's folder was left")
        self.assertFalse(os.path.exists(waiting.job_dir), "a waiting job's folder was left")
        self.assertIsNotNone(running._proc.poll(), "husk outlived the session")


class AFailedStageWriteLeavesNoFolder(unittest.TestCase):
    """`render_batch` removes its job folder on every way out of the stage write."""

    def test_any_exception_from_the_write_takes_the_folder(self):
        _patch_viewer(self)
        made = []
        real = thumbs.tempfile.mkdtemp

        def recorded(*args, **kwargs):
            made.append(real(*args, **kwargs))
            return made[-1]

        def failing(scaffold, items, out_dir):
            raise OSError("disk full")

        prefs = test_support.fixture_prefs(self)
        material = hou.node("/mat").createNode("subnet")
        self.addCleanup(test_support.drop_node, material)
        material.createNode("mtlxstandard_surface")
        with mock.patch.object(thumbs.tempfile, "mkdtemp", recorded), \
                mock.patch.object(preview, "write_batch", failing):
            with self.assertRaises(OSError):
                thumbs.ThumbNailRenderer.render_batch(
                    prefs, "Karma", [("FOLDER_PROBE", material)])
        self.assertEqual(1, len(made), "premise: no job folder was made")
        self.addCleanup(shutil.rmtree, made[0], True)
        self.assertFalse(os.path.exists(made[0]), "a failed write left its job folder")


class ThePreFrameScriptBindsFrameNsMaterial(unittest.TestCase):

    def test_frame_two_binds_the_second_material(self):
        from pxr import Sdf, Usd, UsdGeom, UsdShade
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/ball")
        mesh = UsdGeom.Mesh.Define(stage, "/ball/mesh")
        prims = ["/materials/a", "/materials/b"]
        for path in prims:
            UsdShade.Material.Define(stage, path)
        script = husk_job.PREFRAME % {"prims": prims, "ball": "/ball"}
        self.addCleanup(hou.setFrame, hou.frame())
        hou.setFrame(2)
        exec(compile(script, "preframe", "exec"), {"stage": stage})
        bound = UsdShade.MaterialBindingAPI(mesh.GetPrim()).ComputeBoundMaterial()[0]
        self.assertEqual(Sdf.Path("/materials/b"), bound.GetPath(),
                         "frame 2 did not render the second material")


class OneHuskRendersEachMaterial(unittest.TestCase):
    """Real renders through `render_batch`, here in hython where it runs to the end."""

    def setUp(self):
        _patch_viewer(self)
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.rendersize = 64

    def _render(self, renderer, items):
        before = set(hou.node("/obj").children())
        self.assertTrue(thumbs.ThumbNailRenderer.render_batch(self.prefs, renderer, items))
        self.assertEqual(before, set(hou.node("/obj").children()),
                         "the batch left nodes behind in /obj")
        self.assertFalse(husk_job.jobs.busy())
        return [_hue(tile_icons.thumbnail_path(self.prefs, asset_id)) for asset_id, _ in items]

    def test_two_karma_materials_are_two_pictures(self):
        items = [("RED_PROBE", _plastic(self, RED)), ("GREEN_PROBE", _plastic(self, GREEN))]
        self.assertEqual(["red", "green"], self._render("Karma", items),
                         "one husk did not give each frame its own material")

    @unittest.skipUnless(test_support.renderer_loaded("Octane"), "the Octane plugin is not loaded")
    def test_two_octane_materials_are_two_pictures(self):
        items = [("RED_OCT", _octane(self, RED)), ("GREEN_OCT", _octane(self, GREEN))]
        self.assertEqual(["red", "green"], self._render("Octane", items),
                         "Octane kept the first material for the second frame")


class TheBackgroundQueue(unittest.TestCase):
    """The panel's path: husk runs while Qt's event loop runs; progress, each PNG, and Cancel."""

    def setUp(self):
        _patch_viewer(self)
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.rendersize = 64
        patcher = mock.patch.object(hou, "isUIAvailable", lambda: True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(husk_job.jobs.stop_now)

    def _connect(self, signal, slot):
        signal.connect(slot)
        self.addCleanup(signal.disconnect, slot)

    def _wait_idle(self, seconds):
        loop = QtCore.QEventLoop()

        def idle(active):
            if not active:
                loop.quit()

        self._connect(husk_job.jobs.activeChanged, idle)
        QtCore.QTimer.singleShot(int(seconds * 1000), loop.quit)
        if husk_job.jobs.busy():
            loop.exec()

    def test_progress_and_each_thumbnail_arrive(self):
        written, progress = [], []

        def on_written(asset_id):
            written.append(asset_id)

        def on_progress(done, total):
            progress.append(done)

        self._connect(husk_job.jobs.thumbnailWritten, on_written)
        self._connect(husk_job.jobs.progressed, on_progress)
        items = [("RED_BG", _plastic(self, RED)), ("GREEN_BG", _plastic(self, GREEN))]
        self.assertTrue(thumbs.ThumbNailRenderer.render_batch(self.prefs, "Karma", items))
        self.assertTrue(husk_job.jobs.busy(), "render_batch waited for husk in the foreground")
        self._wait_idle(120)
        self.assertFalse(husk_job.jobs.busy(), "husk did not finish in 120 s")
        self.assertEqual(["RED_BG", "GREEN_BG"], written)
        self.assertEqual(100, max(progress), progress)

    def test_cancel_stops_husk_and_keeps_the_old_pictures(self):
        self.prefs.rendersize = 512    # slow enough to cancel mid-way
        items = [("A_CANCEL", _plastic(self, RED)), ("B_CANCEL", _plastic(self, GREEN))]
        old = []
        for asset_id, _ in items:
            path = tile_icons.thumbnail_path(self.prefs, asset_id)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(b"old picture")
            old.append(path)
        started = []

        def cancel_on_first(done, total):
            if not started:
                started.append(time.monotonic())
                husk_job.jobs.cancel()

        self._connect(husk_job.jobs.progressed, cancel_on_first)
        self.assertTrue(thumbs.ThumbNailRenderer.render_batch(self.prefs, "Karma", items))
        job = husk_job.jobs._running
        self._wait_idle(120)
        self.assertTrue(started, "husk reported no progress to cancel on")
        self.assertFalse(husk_job.jobs.busy())
        self.assertEqual("cancelled", job.status)
        self.assertLess(time.monotonic() - started[0], 5.0, "Cancel did not stop husk")
        self.assertFalse(os.path.exists(job.job_dir), "the job's folder was left behind")
        for path in old:
            with open(path, "rb") as fh:
                self.assertEqual(b"old picture", fh.read(),
                                 "a cancelled render replaced a thumbnail")


if __name__ == "__main__":
    unittest.main()
