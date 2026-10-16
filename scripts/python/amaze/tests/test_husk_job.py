"""One background husk per batch: command, per-frame swap, progress, Cancel. ▸r/husk-startup"""

import os
import sys
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

from amaze import preview  # noqa: E402
from amaze.core import tile_icons  # noqa: E402
from amaze.render import husk_job, thumbs  # noqa: E402
from amaze.tests import test_support  # noqa: E402

OCIO = {"display": hou.Color.ocio_defaultDisplay(), "view": hou.Color.ocio_defaultView(),
        "space": "scene_linear"}
RED, GREEN = (0.8, 0.05, 0.05), (0.05, 0.8, 0.05)
PLASTIC = "139888337459841200"    # a fixture whose surface takes its colour from a parm
OCTANE_SHADER = "octane::NT_MAT_STANDARD_SURFACE"


def _octane_available():
    try:
        return hou.vopNodeTypeCategory().nodeType(OCTANE_SHADER) is not None
    except Exception:                                        # noqa: BLE001
        return False


def _drop(node):
    with hou.undos.disabler():
        try:
            node.destroy()
        except hou.ObjectWasDeleted:
            pass


def _patch_viewer(testcase):
    """Headless there is no Scene Viewer: both seams that read one answer this OCIO."""
    for target in (preview.thumbnail_scene, preview):
        patcher = mock.patch.object(target, "ocio_from_viewer", lambda: dict(OCIO))
        patcher.start()
        testcase.addCleanup(patcher.stop)


def _plastic(testcase, colour):
    """The plastic fixture in a plain holder, its base colour set."""
    holder = hou.node("/mat").createNode("subnet")
    testcase.addCleanup(_drop, holder)
    holder.loadItemsFromFile(os.path.join(test_support.FIXTURE_DIR, "mat", PLASTIC + ".mat"))
    surface = next(c for c in holder.children() if c.type().name() == "mtlxstandard_surface")
    surface.parmTuple("base_color").set(colour)
    return holder


def _octane(testcase, colour):
    import octane_material_builder
    builder = octane_material_builder.createMaskedOctaneSubnet(target_node=hou.node("/mat"))
    testcase.addCleanup(_drop, builder)
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

    def test_karma_skips_both_other_renderers_plugins(self):
        self.assertEqual("{redshift4houdini.*,Houdini_Octane*}",
                         husk_job.plugin_exclusion("Karma"))

    def test_octane_keeps_its_own_plugin(self):
        """Octane aborts without its own Houdini plugin; only Redshift's goes."""
        self.assertEqual("redshift4houdini.*", husk_job.plugin_exclusion("Octane"))

    def test_a_pattern_already_set_is_kept(self):
        self.assertEqual("{mine*,redshift4houdini.*}",
                         husk_job.plugin_exclusion("Octane", "mine*"))
        self.assertEqual("{a,b}", husk_job.plugin_exclusion("Karma", "{a,b}"))

    def test_the_environment_carries_the_exclusion(self):
        with mock.patch.dict(os.environ, {husk_job.EXCLUDE: ""}):
            env = self._job("Karma").environment()
        self.assertEqual(husk_job.plugin_exclusion("Karma"), env[husk_job.EXCLUDE])

    def test_one_husk_renders_every_frame_with_progress(self):
        cmd = self._job("Karma", 3).command()
        self.assertEqual(["-f", "1", "-n", "3"], cmd[cmd.index("-f"):cmd.index("-f") + 4])
        self.assertIn("1a", cmd[cmd.index("-V") + 1])    # `a` prints ALF_PROGRESS
        self.assertTrue(cmd[cmd.index("-o") + 1].endswith("frame.$F4.exr"))
        self.assertIn("--preframe-script", cmd)
        self.assertIn("--postframe-script", cmd)
        self.assertEqual("/x/__render__.usd", cmd[-1])

    def test_only_octane_restarts_its_renderer_every_frame(self):
        """Octane keeps frame 1's material unless restarted ▸r/husk-startup."""
        self.assertNotIn("--restart-delegate", self._job("Karma").command())
        octane = self._job("Octane").command()
        self.assertEqual("1", octane[octane.index("--restart-delegate") + 1])

    def test_a_script_path_with_a_space_is_quoted(self):
        self.assertEqual('"/a b/p.py"', husk_job._script_arg("/a b/p.py"))
        self.assertEqual("/ab/p.py", husk_job._script_arg("/ab/p.py"))


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

    @unittest.skipUnless(_octane_available(), "the Octane plugin is not loaded")
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
