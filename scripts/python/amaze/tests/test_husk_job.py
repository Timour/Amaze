"""One background husk per batch: command, material per frame, progress, Cancel. ▸r/husk-startup"""

import os
import shutil
import sys
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze import preview  # noqa: E402
from amaze.render import husk_job, thumbs  # noqa: E402
from amaze.tests import test_support  # noqa: E402

OCIO = {"display": hou.Color.ocio_defaultDisplay(), "view": hou.Color.ocio_defaultView(),
        "space": "scene_linear"}


def _patch_viewer(testcase):
    """Headless there is no Scene Viewer: both `ocio_from_viewer` functions return this OCIO."""
    for target in (preview.thumbnail_scene, preview):
        patcher = mock.patch.object(target, "ocio_from_viewer", lambda: dict(OCIO))
        patcher.start()
        testcase.addCleanup(patcher.stop)


class TheCommandAndItsEnvironment(unittest.TestCase):

    def _job(self, renderer, count=3):
        batch = {"usd": "/x/__render__.usd", "prims": ["/m%d" % i for i in range(count)],
                 "ball": "/ball", "renderer": renderer, "ocio": ("d", "v", "s")}
        return husk_job.HuskJob(batch, "/x", [("id%d" % i, "/p%d.png" % i)
                                              for i in range(count)])

    def test_the_environment_is_the_one_houdini_gives_its_own_husk(self):
        """Read live, as a USD Render ROP passes it, not Python's copy ▸r/husk-foreign-shader-plugins"""
        os.putenv("AMAZE_SET_AFTER_START", "1")    # what Houdini does to MATERIALX_SEARCH_PATH
        try:
            env = self._job("Karma").environment()
        finally:
            os.unsetenv("AMAZE_SET_AFTER_START")
        self.assertEqual("1", env.get("AMAZE_SET_AFTER_START"))
        for switch in ("PXR_SDR_DISABLE_PLUGINS", "HOUDINI_DSO_EXCLUDE_PATTERN"):
            self.assertEqual(os.environ.get(switch), env.get(switch), switch)

    def test_a_redshift_husk_keeps_its_own_cache_and_log(self):
        """Its local data path is its own folder under Amaze's cache, apart from the session's."""
        from amaze.helpers import hostos
        env = self._job("Redshift").environment()
        self.assertEqual(os.path.join(hostos.cache_root(), "redshift"),
                         env["REDSHIFT_LOCALDATAPATH"])
        self.assertTrue(os.path.isdir(env["REDSHIFT_LOCALDATAPATH"]))
        from PySide6.QtCore import QProcessEnvironment
        live = QProcessEnvironment.systemEnvironment()
        session = live.value("REDSHIFT_LOCALDATAPATH") if live.contains("REDSHIFT_LOCALDATAPATH") else None
        self.assertEqual(session,
                         self._job("Karma").environment().get("REDSHIFT_LOCALDATAPATH"),
                         "a Karma husk changed the session's Redshift path")

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

    def test_the_progress_bar_counts_over_the_batch_not_per_frame(self):
        """husk counts each frame from 0 to 100; three frames must not fill the bar three times."""
        job = self._job("Karma", 3)
        seen = []
        job.progressed.connect(lambda done, total: seen.append(done))
        for line in ("%s 50%%" % husk_job.PROGRESS, "%s 1" % husk_job.DONE,
                     "%s 0%%" % husk_job.PROGRESS, "%s 50%%" % husk_job.PROGRESS,
                     "%s 2" % husk_job.DONE, "%s 100%%" % husk_job.PROGRESS):
            job._handle(line)
        self.assertEqual([16, 33, 50, 100], seen)
        self.assertEqual(seen, sorted(seen), "the progress value went down")

    def test_a_script_path_with_a_space_is_quoted(self):
        self.assertEqual('"/a b/p.py"', husk_job._script_arg("/a b/p.py"))
        self.assertEqual("/ab/p.py", husk_job._script_arg("/ab/p.py"))


class ARenderSucceedsOrFailsByItsFramesDone(unittest.TestCase):
    """22.0.482's husk exits 139 after its last frame ▸r/husk-startup; a fake husk does the same."""

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
        self.assertEqual([], log.matching("render stopped"), "a finished render logged `render stopped`")
        finished = [(r["data"].get("status"), r["data"].get("code"))
                    for r in log.records("thumb") if r["msg"] == "husk finished"]
        self.assertEqual([("done", 139)], finished, "the log lost husk's exit code")

    def test_an_exit_before_the_last_frame_is_a_failure(self):
        job, log = self._run(2)
        self.assertEqual("failed: husk exit 139", job.status)
        self.assertEqual(1, len(log.matching("render stopped (husk exit 139)")),
                         "a render missing a frame was not logged as stopped")


class AFrameWithNoPictureIsRecorded(unittest.TestCase):
    """A frame husk reports done with no EXR, or one that converts to no PNG, is logged."""

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
        self.assertEqual([], written, "`thumbnailWritten` was emitted with no picture written")
        return [(r["data"].get("asset_id"), r["data"].get("frame"))
                for r in log.records("thumb") if r["data"].get("frame") is not None]

    def test_a_missing_exr_is_logged_per_frame(self):
        self.assertEqual([("NO_EXR_1", 1), ("NO_EXR_2", 2)], self._run(write_exr=False))

    def test_an_exr_that_converts_to_nothing_is_logged(self):
        self.assertEqual([("NO_EXR_1", 1), ("NO_EXR_2", 2)], self._run(write_exr=True))


class QuittingLeavesNoJobFolder(unittest.TestCase):
    """At Houdini's exit the running husk is stopped and every job's folder is removed."""

    def _sleeping_job(self, jobs):
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
        running, waiting = self._sleeping_job(jobs), self._sleeping_job(jobs)
        self.addCleanup(lambda: running._proc and running._proc.kill())
        self.addCleanup(lambda: running._timer and running._timer.stop())
        self.assertIs(running, jobs._running, "premise: the first job is not the running one")
        self.assertTrue(os.path.isdir(waiting.job_dir), "premise: no waiting folder")
        jobs.stop_now()
        self.assertFalse(os.path.exists(running.job_dir), "the running job's folder was left")
        self.assertFalse(os.path.exists(waiting.job_dir), "a waiting job's folder was left")
        self.assertIsNotNone(running._proc.poll(), "husk still runs after stop_now")


class AFailedStageWriteLeavesNoFolder(unittest.TestCase):
    """`render_batch` removes its job folder whatever exception the stage write raises."""

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
        self.assertTrue(stage.GetPrimAtPath("/ball").HasAPI(UsdShade.MaterialBindingAPI),
                        "the binding was authored without applying its API schema")


class AHuskThatWillNotStopIsKilled(unittest.TestCase):
    """A Redshift husk stuck in a texture conversion ignored SIGTERM. ▸r/redshift-thumbnail-paths"""

    def _job_that_ignores_sigterm(self):
        folder = test_support.scratch_dir("amaze_husk_deaf_")
        self.addCleanup(shutil.rmtree, folder, True)
        job = husk_job.HuskJob({"usd": "", "prims": [], "ball": "", "renderer": "Redshift"},
                               folder, [("DEAF", "")])
        husk = [test_support.plain_python(), "-c",
                "import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                "print('ready', flush=True)\ntime.sleep(120)\n"]
        patcher = mock.patch.object(job, "command", lambda: husk)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(lambda: job._proc and job._proc.poll() is None and job._proc.kill())
        return job

    def test_cancel_kills_after_the_grace(self):
        job = self._job_that_ignores_sigterm()
        with mock.patch.object(husk_job, "KILL_AFTER", 1.0):
            threading.Timer(1.0, job.cancel).start()
            started = time.monotonic()
            job.run_blocking()
        self.assertEqual("cancelled", job.status)
        self.assertIsNotNone(job._proc.poll(), "the husk still runs after cancel")
        self.assertLess(time.monotonic() - started, 15.0, "the kill took 15 s or more")

    def test_a_husk_with_no_output_is_stalled_and_killed(self):
        job = self._job_that_ignores_sigterm()
        with mock.patch.object(husk_job, "STALL_SECONDS", 2), \
                mock.patch.object(husk_job, "KILL_AFTER", 1.0), \
                test_support.captured_log() as log:
            started = time.monotonic()
            job.run_blocking()
        self.assertEqual("failed: stalled", job.status)
        self.assertIsNotNone(job._proc.poll(), "the stalled husk was left running")
        self.assertLess(time.monotonic() - started, 15.0, "the stall took 15 s or more to detect")
        self.assertEqual(1, len(log.matching("printed nothing")), "the stall was not logged")


if __name__ == "__main__":
    unittest.main()
