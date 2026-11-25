"""Tile pictures and captures: one test per requirement in docs/requirements/tile-pictures.md."""

import errno
import importlib
import os
import shutil
import sys
import threading
import time
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

try:
    import hou
    HOUDINI = True
except ImportError:    # without Houdini: the engine modules import it; no test here runs it
    hou = sys.modules["hou"] = types.ModuleType("hou")
    HOUDINI = False

from amaze import messages  # noqa: E402
from amaze.core import guard, library_files, scene_captures, thumbnails, tile_icons  # noqa: E402
from amaze.core import texture_library, workers  # noqa: E402
from amaze.helpers import hostos  # noqa: E402
from amaze.render import husk_job  # noqa: E402
from amaze.tests import faults, test_support  # noqa: E402

needs_houdini = unittest.skipUnless(HOUDINI, "renders and scenes need Houdini")
ANNA = "u-anna"
OLD = b"the picture the tile showed before"


def png(*colours: str, size: int = 8) -> bytes:
    """A PNG's bytes: the first colour, with one pixel of each other."""
    image = QtGui.QImage(size, size, QtGui.QImage.Format.Format_RGB32)
    image.fill(QtGui.QColor(colours[0]))
    for n, colour in enumerate(colours[1:]):
        image.setPixelColor(n, n, QtGui.QColor(colour))
    data = QtCore.QBuffer()
    data.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    image.save(data, "PNG")
    return bytes(data.data())


NEW, FLAT = png("#204060", "#f0c020"), png("#000000")


def write(data: bytes):
    """A renderer that writes `data` whole to its output."""
    def made(path, *_args, **_kwargs):
        with open(path, "wb") as handle:
            handle.write(data)
    return made


def torn(path, *_args, **_kwargs):
    """A renderer cut off halfway through its output, as when Houdini crashes."""
    with open(path, "wb") as handle:
        handle.write(NEW[: len(NEW) // 2])
    raise faults.Cut()


def full(path, *_args, **_kwargs):
    raise OSError(errno.ENOSPC, "No space left on device", path)


class Viewer:
    """A Scene View: its size, and the renderer drawing it."""

    def __init__(self, size=(600, 300), renderer="Houdini VK"):
        self.size, self.renderer = size, renderer

    def curViewport(self):
        return types.SimpleNamespace(resolutionInPixels=lambda: self.size, name=lambda: "persp1",
                                     camera=lambda: None)

    def currentHydraRenderer(self):
        return self.renderer

    def isRendererPaused(self):
        return False


def capturing(made):
    """Houdini's viewport capture, which writes through `made(path)`; its calls are recorded."""
    calls = []

    def save(sceneviewer=None, output="", croptocamera=True, res=(0, 0)):
        calls.append(res)
        made(output)
    utils = types.ModuleType("husd.assetutils")
    utils.saveThumbnailFromViewer = save
    package = types.ModuleType("husd")
    package.assetutils = utils
    return mock.patch.dict(sys.modules, {"husd": package, "husd.assetutils": utils}), calls


def batch() -> dict:
    """What a job's batch holds, for a stand-in husk that reads none of it."""
    return {"renderer": "Karma", "prims": [], "ball": "", "ocio": None, "user": ANNA}


def on(disk):
    """Every guard made meanwhile writes through `disk`."""
    real = guard.Disk
    return mock.patch.object(guard, "Disk", lambda: disk or real())


class _Library(unittest.TestCase):
    """A library whose material A1 has a picture, and Anna as its user."""

    def setUp(self):
        self.dir = test_support.scratch_dir("amaze_pictures_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        test_support.put(self.dir, guard.MASTER, {"users": {ANNA: {"name": "Anna"}}})
        test_support.put(self.dir, "materials/Brick__A1/A1.mat", b"nodes of A1")
        self.picture = test_support.put(self.dir, "materials/Brick__A1/A1.png", OLD)
        self.prefs = types.SimpleNamespace(dir=self.dir, library_user=ANNA)

    def shown(self, path: str = "") -> bytes:
        with open(path or self.picture, "rb") as handle:
            return handle.read()

    def scratch_left(self) -> list:
        return [name for _here, _dirs, names in os.walk(self.dir) for name in names
                if library_files.is_scratch(name)]

    def husk(self, job_dir: str, frames, script: str):
        """A job whose stand-in husk runs `script`; preview's EXR to PNG writes NEW."""
        from amaze import preview
        job = husk_job.HuskJob(batch(), job_dir, frames)
        for patcher in (mock.patch.object(job, "command", lambda: [
                test_support.plain_python(), "-c", script]),
                mock.patch.object(preview, "exr_to_png", lambda exr, out, *a: write(NEW)(out))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(lambda: job._proc and job._proc.poll() is None and job._proc.kill())
        return job


class PicturesTest(_Library):

    def rendered(self, made):
        """The render route: husk finished frame 1, whose EXR preview turns into the picture."""
        from amaze import preview
        job_dir = test_support.scratch_dir("amaze_job_")
        self.addCleanup(shutil.rmtree, job_dir, True)
        job = husk_job.HuskJob(batch(), job_dir, [("A1", self.picture)])
        test_support.put(job_dir, "f1.exr", b"exr")
        with mock.patch.object(preview, "exr_to_png", lambda exr, out, *a: made(out)):
            husk_job.Jobs()._frame_done(job, 1)

    def captured(self, made):
        patcher, _calls = capturing(made)
        with patcher:
            scene_captures.capture_viewport(self.picture, Viewer(), ANNA)

    def imported(self, made):
        """An online import's own picture, saved as the asset's."""
        from amaze.render import nodes
        image = QtGui.QImage.fromData(NEW)
        with mock.patch.object(QtGui.QImage, "save", lambda _image, path, *a: made(path) or True):
            nodes.NodeHandler(self.prefs)._put_picture(image, lambda: self.picture)

    @needs_houdini
    def test_tp01_every_new_picture_is_put_in_place_whole(self):
        faulted = (("cut mid-write", torn, None), ("full disk", full, None),
                   ("cut at the swap", write(NEW), lambda: faults.FaultDisk(cut_at=1)),
                   ("held by a program", write(NEW), lambda: faults.FaultDisk(busy="A1.png")),
                   ("no fault", write(NEW), None))
        for route in (self.rendered, self.captured, self.imported):
            for fault, made, disk in faulted:
                with self.subTest(route=route.__name__, fault=fault):
                    test_support.put(self.dir, "materials/Brick__A1/A1.png", OLD)
                    with on(disk and disk()):
                        try:
                            route(made)
                        except (faults.Cut, scene_captures.CaptureRefused):
                            pass
                    guard.Guard(self.dir)    # opened again, as after a crash
                    self.assertEqual(NEW if fault == "no fault" else OLD, self.shown())
                    self.assertEqual([], self.scratch_left())

    @needs_houdini
    def test_tp02_a_stopped_render_or_a_refused_capture_leaves_the_old_picture(self):
        second = test_support.put(self.dir, "materials/Stone__A2/A2.png", OLD)
        frames = [("A1", self.picture), ("A2", second)]
        script = ("import os, sys, time\nopen(os.path.join(%r, 'f1.exr'), 'wb').write(b'x')\n"
                  "print('%s 1', flush=True)\n"
                  "open(os.path.join(%r, 'f2.exr'), 'wb').write(b'ha')\n%s\n")
        for how, ending in (("cancelled", "time.sleep(60)"), ("stalled", "time.sleep(60)"),
                            ("failed", "sys.exit(1)"), ("quit", "time.sleep(60)")):
            with self.subTest(how), mock.patch.object(husk_job, "KILL_AFTER", 1.0), \
                    mock.patch.object(husk_job, "STALL_SECONDS", 2 if how == "stalled" else 600):
                for path in (self.picture, second):
                    test_support.put(os.path.dirname(path), os.path.basename(path), OLD)
                job_dir = test_support.scratch_dir("amaze_job_")
                job, jobs = self.husk(job_dir, frames, script % (
                    job_dir, husk_job.DONE, job_dir, ending)), husk_job.Jobs()
                if how == "quit":
                    jobs.submit(job)
                    test_support.pump_until(lambda: self.shown() == NEW)
                    jobs.stop_now()
                else:
                    if how == "cancelled":
                        threading.Timer(2.0, job.cancel).start()
                    jobs.submit(job, blocking=True)
                self.assertEqual((NEW, OLD), (self.shown(), self.shown(second)))
                self.assertFalse(os.path.exists(job_dir), "the job folder was left")
        for why, viewer, made, user in (
                ("rendering", Viewer(renderer="Karma XPU"), write(NEW), ANNA),
                ("flat", Viewer(), write(FLAT), ANNA), ("no user", Viewer(), write(NEW), "")):
            patcher, _calls = capturing(made)
            with self.subTest(why), patcher, mock.patch.object(
                    scene_captures, "scene_viewer", lambda: viewer):
                with self.assertRaises(scene_captures.CaptureRefused):
                    scene_captures.capture_tile(self.picture, "A1", user)
                self.assertEqual(NEW, self.shown(), "a refused capture changed the picture")

    def test_tp10_a_picture_goes_only_to_the_asset_it_was_made_for(self):
        target = tile_icons.thumbnail_path(self.prefs, "A1", library_files.MATERIALS)
        self.assertEqual(self.picture, target)
        renamed = os.path.join(self.dir, "materials", "Granite__A1")
        os.rename(os.path.dirname(self.picture), renamed)    # during its render
        self.assertTrue(guard.put_rendered(target, write(NEW), ANNA))
        self.assertEqual(NEW, self.shown(os.path.join(renamed, "A1.png")))
        shutil.rmtree(renamed)    # deleted during its render
        self.assertFalse(guard.put_rendered(target, write(NEW), ANNA))
        self.assertEqual([], os.listdir(os.path.join(self.dir, "materials")),
                         "a deleted asset got a picture, or a folder")
        outside = test_support.scratch_dir("amaze_outside_")
        self.addCleanup(shutil.rmtree, outside, True)
        try:
            os.symlink(outside, os.path.join(self.dir, "materials", "Away__A3"))
            unsafe = ("../../outside", "..", "a/b", "A3")
        except (OSError, NotImplementedError):    # Windows without the right to make a link
            unsafe = ("../../outside", "..", "a/b")
        for asset_id in unsafe:
            with self.subTest(asset_id), self.assertRaises(hostos.PathOutsideBase):
                tile_icons.thumbnail_path(self.prefs, asset_id, library_files.MATERIALS)

    @needs_houdini
    def test_tp11_a_render_leaves_the_users_scene_as_it_found_it(self):
        from amaze import preview
        from amaze.actions import nodes as node_actions
        from amaze.core import cop_library, library, renderers
        from amaze.helpers import wording
        from amaze.render import thumbs
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        prefs = test_support.fixture_prefs(self)
        prefs.render_on_import, prefs.rendersize = 0, 16
        ocio = {"display": "sRGB - Display", "view": "ACES 1.0 - SDR Video", "space": "ACEScg"}
        submitted = []
        for patcher in (
                mock.patch.object(preview.thumbnail_scene, "ocio_from_viewer", lambda: ocio),
                mock.patch.object(preview, "ocio_from_viewer", lambda: ocio),
                mock.patch.object(husk_job.jobs, "submit", lambda job, **k: submitted.append(job))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(lambda: [job.discard() for job in submitted])
        material = next(m for m in library.MaterialLibrary(preferences=prefs).assets
                        if renderers.is_karma(m.renderer))
        nodes_model = cop_library.CopLibrary(preferences=prefs)
        with hou.undos.disabler():
            box = hou.node("/obj").createNode("geo", "user_box")
            box.createNode("box").setDisplayFlag(True)
        held = test_support.asset_ids(nodes_model)
        node_actions.add_asset(nodes_model, box, "", "", False, name="user_box")
        sop, = test_support.arrived(nodes_model, held)
        with hou.undos.disabler():
            own = hou.node("/mat").createNode("subnet", wording.sanitize_usd_path(material.name))
            own.createNode("null", "keep_me")
            hou.node("/stage").createNode("materiallibrary", "user_materials")
        for node in (own, box, hou.node("/stage/user_materials")):
            self.addCleanup(test_support.drop_node, node)
        box.setSelected(True, clear_all_selected=True)
        scene = {node.path(): node.sessionId() for node in hou.node("/").allSubChildren()}
        hou.undos.clear()
        for render in (thumbs.ThumbNailRenderer(prefs, material).create_thumbnail,
                       lambda: thumbs.ThumbNailRenderer(prefs).create_thumb_sop(str(sop.mat_id))):
            self.assertIsNot(False, render(), "premise: the SOP did not render")
            self.assertEqual(scene, {node.path(): node.sessionId()
                                     for node in hou.node("/").allSubChildren()})
            self.assertEqual((), hou.undos.undoLabels(), "the render is on the undo list")
            self.assertEqual([box], list(hou.selectedNodes()), "the selection changed")
        self.assertEqual(1, len(submitted), "premise: the material did not render")

    def test_tp12_no_render_process_outlives_houdini_or_its_cancel(self):
        deaf = ("import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                "print('ready', flush=True)\ntime.sleep(60)\n")
        with mock.patch.object(husk_job, "KILL_AFTER", 1.0):
            for how in ("cancel", "silent", "quit"):
                job_dir = test_support.scratch_dir("amaze_job_")
                job = husk_job.HuskJob(batch(), job_dir, [("A1", "")])
                started, jobs = time.monotonic(), husk_job.Jobs()
                self.addCleanup(lambda job=job: job._timer and job._timer.stop())
                with self.subTest(how), mock.patch.object(job, "command", lambda: [
                        test_support.plain_python(), "-c", deaf]), mock.patch.object(
                        husk_job, "STALL_SECONDS", 2 if how == "silent" else 600):
                    if how == "quit":
                        jobs.submit(job)
                        waiting = husk_job.HuskJob(
                            batch(), test_support.scratch_dir("amaze_job_"), [])
                        jobs._waiting.append(waiting)
                        jobs.stop_now()
                        self.assertFalse(os.path.exists(waiting.job_dir), "a waiting job was left")
                    else:
                        if how == "cancel":
                            threading.Timer(1.0, job.cancel).start()
                        jobs.submit(job, blocking=True)
                    self.assertIsNotNone(job._proc.poll(), "husk outlived its stop")
                    self.assertFalse(os.path.exists(job_dir), "the job folder was left")
                    self.assertLess(time.monotonic() - started, 12.0, "the stop waited too long")

    @needs_houdini
    def test_tp13_a_capture_is_taken_only_when_the_user_asks(self):
        from amaze.actions import files as files_actions
        from amaze.sections import file as file_section
        scene = os.path.join(test_support.scratch_dir("amaze_scene_"), "shot.hip")
        self.addCleanup(shutil.rmtree, os.path.dirname(scene), True)
        hou.hipFile.save(scene)
        self.addCleanup(hou.hipFile.clear, suppress_save_prompt=True)
        patcher, calls = capturing(write(NEW))
        folders = types.SimpleNamespace(set_scene_folder=lambda folder: None)
        watch = files_actions.watch_scene(folders)
        self.addCleanup(files_actions.unwatch_scene, watch)
        section = file_section.FileSection.__new__(file_section.FileSection)
        files = types.SimpleNamespace(hip_path_for=lambda index: scene)
        section.pane = types.SimpleNamespace(files=files)
        asked = []
        with patcher:
            with mock.patch.object(scene_captures, "capture_viewport",
                                   lambda *a, **k: asked.append(a)):
                section.open_hip_scene(None)
                QtWidgets.QApplication.processEvents()
            self.assertEqual([], asked + calls, "opening a scene took a capture")
            for renderer, taken in (("Karma XPU", False), ("Houdini VK", True)):
                with mock.patch.object(scene_captures, "scene_viewer", lambda: Viewer(
                        renderer=renderer)), self.subTest(renderer):
                    try:
                        scene_captures.capture_tile(self.picture, "A1", ANNA)
                    except scene_captures.CaptureRefused as refused:
                        self.assertTrue(
                            str(refused).startswith(messages.CAPTURE_VIEWPORT_RENDERING))
                    self.assertEqual(taken, bool(calls), "a capture was drawn through " + renderer)

    def test_tp14_a_reload_while_pictures_load_frees_no_running_thread(self):
        from amaze.core import conversion
        source = test_support.put(self.dir, "plate.rat", b"no picture Qt can read")
        slow = (("slow", lambda path, out, ctx: conversion._run_process(
            test_support.plain_python(), ["-c", "import time; time.sleep(30)"],
            cancelled=ctx.cancelled)),)
        with mock.patch.object(conversion, "_FORMAT_ADAPTERS", slow):
            before = thumbnails.engine
            before.request_convert(("reload", source), source, 64)
            test_support.pump_until(lambda: any(t.isRunning() for t in before._threads))
            loaders = list(before._threads)
            self.assertTrue(loaders, "premise: no loader was running")
            importlib.reload(thumbnails)
        self.assertIsNot(before, thumbnails.engine, "premise: the reload kept the engine")
        freed = [t for t in loaders if t.isRunning() and t not in workers._unstoppable]
        self.assertEqual([], freed, "a loader still running lost its last reference")
        stuck = mock.Mock(isRunning=lambda: True, wait=lambda ms: False)
        with mock.patch.object(workers, "WAIT_MS", 10), \
                mock.patch.object(workers, "TERMINATE_MS", 10):
            workers.stop([stuck], "test")
        self.addCleanup(workers._unstoppable.remove, stuck)
        importlib.reload(workers)
        self.assertIn(stuck, workers._unstoppable, "a thread that would not stop was let go")

    @needs_houdini
    def test_tp20_each_material_its_own_picture_in_its_renderer_with_its_samples_one_job_each(self):
        from amaze import preview
        from amaze.actions import materials as material_actions
        from amaze.core import library
        from amaze.preview import thumbnail_scene
        from amaze.render import thumbs
        test_support.pin_env(self, "OCIO", "/dev/null")    # a conversion's save checks it
        prefs = test_support.fixture_prefs(self)
        prefs.karma_rendersamples, prefs.rendersamples, prefs.octane_rendersamples = 7, 9, 11
        model = library.MaterialLibrary(prefs)
        mats = [model.assets[model.find_asset_row_by_id(key)]
                for key in ("139888336889814930", "139888337058723210")]
        target = next((key for key in ("Redshift", "Octane") if test_support.renderer_loaded(key)), "")
        if target:    # a second renderer, where one is loaded
            held = test_support.asset_ids(model)
            ok, report = material_actions.convert(model, model.index(model.find_asset_row_by_id(
                mats[1].mat_id), 0), target, render=False)
            self.assertTrue(ok, report)
            mats += test_support.arrived(model, held)
        jobs, samples, write = [], {}, preview.write_batch
        names = ("samplesperpixel", "redshiftglobalUnifiedMaxSamples",
                 "xn__octaneglobalmaxsamples4_jebg")

        def written(scaffold, items, out_dir):    # the stage as it is written, its samples read
            samples[scaffold["renderer"]] = [node.parm(name).eval() for node in scaffold[
                "net"].allSubChildren() for name in names if node.parm(name) is not None]
            return write(scaffold, items, out_dir)

        viewer = {"display": "sRGB", "view": "Raw", "space": "ACEScg"}
        with mock.patch.object(thumbnail_scene, "ocio_from_viewer", lambda: viewer), \
                mock.patch.object(preview, "ocio_from_viewer", lambda: viewer), \
                mock.patch.object(preview, "write_batch", written), \
                mock.patch.object(husk_job.jobs, "submit", lambda job, **how: jobs.append(job)):
            thumbs.ThumbNailRenderer.render_assets(prefs, mats)
        wanted = {thumbs.usd_renderer(mat): [] for mat in mats}
        for mat in mats:
            wanted[thumbs.usd_renderer(mat)].append((str(mat.mat_id), tile_icons.thumbnail_path(
                prefs, str(mat.mat_id), library_files.MATERIALS)))
        self.assertEqual(wanted, {job.renderer: sorted(job.frames) for job in jobs})
        self.assertEqual(len(wanted), len(jobs), "not one background render per renderer")
        self.assertEqual({renderer: [{"Karma": 7, "Redshift": 9, "Octane": 11}[renderer]]
                          for renderer in wanted}, samples)

    @needs_houdini
    def test_tp21_no_viewer_renders_nothing_and_a_renderer_not_loaded_is_named_once(self):
        from amaze import preview
        from amaze.core import library
        from amaze.preview import thumbnail_scene
        from amaze.render import thumbs
        prefs = test_support.fixture_prefs(self)
        model = library.MaterialLibrary(prefs)
        gold = model.assets[model.find_asset_row_by_id("139888336889814930")]
        mats = [gold] + [types.SimpleNamespace(mat_id=key, name=name, renderer=renderer)
                         for key, name, renderer in (("R1", "Ruby", "Redshift"),
                                                     ("O1", "Opal", "Octane"))]
        said, jobs = [], []
        scene = sorted(node.path() for node in hou.node("/").allSubChildren())
        ui = types.SimpleNamespace(displayMessage=lambda text, **how: said.append(text),
                                   curDesktop=lambda: types.SimpleNamespace(
                                       paneTabOfType=lambda kind: None))
        with mock.patch.object(hou, "ui", ui, create=True), test_support.plugins_loaded(), \
                mock.patch.object(husk_job.jobs, "submit", lambda job, **how: jobs.append(job)):
            thumbs.ThumbNailRenderer.render_assets(prefs, mats)
            self.assertEqual(([messages.NO_SCENE_VIEWER_FOR_THUMBNAIL], [], scene), (said, jobs, sorted(
                node.path() for node in hou.node("/").allSubChildren())), "no viewer, yet it went on")
            said.clear()
            viewer = {"display": "sRGB", "view": "Raw", "space": "ACEScg"}    # one is open now
            with mock.patch.object(thumbnail_scene, "ocio_from_viewer", lambda: viewer), \
                    mock.patch.object(preview, "ocio_from_viewer", lambda: viewer):
                thumbs.ThumbNailRenderer.render_assets(prefs, mats)
        self.assertEqual(1, len(said), said)
        self.assertTrue("Ruby" in said[0] and "Opal" in said[0], said)
        self.assertEqual([str(gold.mat_id)], [key for job in jobs for key, _path in job.frames])

    @needs_houdini
    def test_tp24_a_files_capture_is_one_file_in_the_library_and_stays_through_a_save(self):
        import hashlib
        from amaze.core import captures, file_library, locations
        from amaze.prefs import prefs as prefs_mod
        self.prefs = prefs_mod.Prefs()    # what the File grid reads too
        self.prefs.dir, self.prefs.library_user = self.dir, ANNA
        self.prefs.path = test_support.scratch_dir("amaze_settings_")
        self.addCleanup(shutil.rmtree, self.prefs.path, True)
        shots = test_support.scratch_dir("amaze_shots_")
        self.addCleanup(shutil.rmtree, shots, True)
        self.addCleanup(hou.hipFile.clear, suppress_save_prompt=True)
        scene = os.path.join(shots, "shot" + scene_captures.scene_extension())
        self.assertTrue(locations.register(self.prefs, shots))
        hou.hipFile.save(scene)
        patcher, _calls = capturing(write(NEW))
        with patcher, mock.patch.object(scene_captures, "scene_viewer", lambda: Viewer()):
            taken = scene_captures.capture_open_scene(self.prefs)    # the shelf tool
        key = captures.file_key(self.prefs, scene)
        self.assertEqual(os.path.join(self.dir, "files", hashlib.sha1(key.encode()).hexdigest()
                                      + ".png"), taken)
        grid = file_library.FileFiles(self.prefs)
        grid.set_folder(shots)
        self.assertEqual(taken, grid.capture_path(grid.row_for_path(scene)), "the tile reads another")
        elsewhere = test_support.scratch_dir("amaze_shots_")    # the same folder on another computer
        self.addCleanup(shutil.rmtree, elsewhere, True)
        os.rmdir(elsewhere)
        os.rename(shots, elsewhere)
        self.assertTrue(locations.relocate_record(self.prefs, shots, elsewhere))
        moved = os.path.join(elsewhere, os.path.basename(scene))
        self.assertEqual(taken, captures.file_path(self.prefs, captures.file_key(self.prefs, moved)))
        hou.hipFile.save(moved)
        self.assertEqual(NEW, self.shown(taken), "the capture went when the scene was saved again")

    def test_tp25_only_the_open_saved_scene_is_captured(self):
        saved = test_support.put(self.dir, "shots/saved.hip", b"scene")
        taken = []
        with mock.patch.object(scene_captures, "capture_tile",
                               lambda out, key, user: taken.append(out)):
            for opened, target, refused in (
                    ("", "", messages.CAPTURE_NO_SCENE),
                    (saved, "/elsewhere/other.hip", messages.CAPTURE_OTHER_SCENE),
                    (saved + ".unsaved", "", messages.CAPTURE_SCENE_UNSAVED)):
                with self.subTest(refused), mock.patch.object(
                        scene_captures, "current_scene_path", lambda: opened):
                    with self.assertRaises(scene_captures.CaptureRefused) as caught:
                        scene_captures.capture_open_scene(self.prefs, target)
                    self.assertEqual(refused, str(caught.exception))
            self.assertEqual([], taken)
            with mock.patch.object(scene_captures, "current_scene_path", lambda: saved), \
                    mock.patch("amaze.core.locations.file_ident", lambda prefs, path: ""):
                scene_captures.capture_open_scene(self.prefs)
        self.assertEqual(os.path.join(self.dir, "files"), os.path.dirname(taken[0]))

    def test_tp26_a_new_picture_shows_and_a_late_one_never_replaces_it(self):
        from amaze.core import captures, model_registry
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        prefs = test_support.fixture_prefs(self)
        self.addCleanup(model_registry.release, prefs)
        model = model_registry.models_for(prefs)["material_model"]
        self.assertIs(model, model_registry.models_for(prefs)["material_model"],
                      "a second panel has a model of its own, which no new picture reaches")
        painted, shown = [], model._thumb_key(0)
        model.dataChanged.connect(lambda first, last, roles=(): painted.append(first.row()))
        before = thumbnails.engine.generation(shown)
        captures.signal_capture_saved(model.tile_key(0))
        self.assertIn(0, painted, "the tile was not repainted")
        self.assertGreater(thumbnails.engine.generation(shown), before, "the old picture stays")
        engine = thumbnails.ThumbnailEngine()
        self.addCleanup(engine.shutdown)
        key, delivered = ("library", "A1"), []
        engine.request_file(key, self.picture)
        old = thumbnails._FileLoader(list(engine._file_queue))
        engine._file_queue = []
        old.loaded.connect(lambda *delivery: delivered.append(delivery))
        test_support.put(self.dir, "materials/Brick__A1/A1.png", FLAT)
        old.run()    # read the old picture; its delivery waits
        test_support.put(self.dir, "materials/Brick__A1/A1.png", NEW)
        engine.discard(key)    # a new picture was written
        engine.request_file(key, self.picture)
        fresh = thumbnails._FileLoader(list(engine._file_queue))
        engine._file_queue = []
        fresh.loaded.connect(engine._on_loaded)
        fresh.run()
        engine._on_loaded(*delivered[0])    # the old one arrives last
        self.assertEqual(QtGui.QImage.fromData(NEW), engine.peek(key), "a late picture won")

    def test_tp27_two_libraries_never_share_a_picture(self):
        from amaze.core import library
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        one = test_support.fixture_prefs(self)
        model = library.MaterialLibrary(preferences=one)
        here = (model._thumb_key(0), tile_icons.tile_read_path(one, model.assets[0].mat_id,
                                                                library_files.MATERIALS))
        one.dir = test_support.fresh_library(self)
        there = (model._thumb_key(0), tile_icons.tile_read_path(one, model.assets[0].mat_id,
                                                                 library_files.MATERIALS))
        self.assertNotEqual(here[0], there[0], "one cache key for two libraries")
        self.assertNotEqual(here[1], there[1], "one picture file for two libraries")

    def test_tp28_a_tile_finds_its_picture_without_touching_the_disk(self):
        from amaze.core import model_registry
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        prefs = test_support.fixture_prefs(self)
        self.addCleanup(model_registry.release, prefs)
        model = model_registry.models_for(prefs)["material_model"]
        touched = []

        def counted(real):
            return lambda *a, **k: touched.append(a[:1]) or real(*a, **k)
        with mock.patch.object(os, "stat", counted(os.stat)), \
                mock.patch.object(os, "lstat", counted(os.lstat)), \
                mock.patch.object(os, "listdir", counted(os.listdir)), \
                mock.patch.object(os, "scandir", counted(os.scandir)):
            pictures = [model.tile_picture(row) for row in range(model.rowCount())]
            for path, key, _fills in (one for picture in pictures for one in picture.files):
                self.assertIsNone(thumbnails.engine.request_file(key, path), "read while painting")
        self.assertEqual([], touched, "painting the tiles touched the disk")
        row = next(n for n, asset in enumerate(model.assets) if asset.name == "Bricks")
        model.set_tile_name(row, "Renamed Brick")    # its folder follows, in the save
        folder = os.path.dirname(model.tile_picture(row).files[0][0])
        self.assertTrue(os.path.basename(folder).startswith("Renamed Brick__"), folder)
        self.assertTrue(os.path.isdir(folder), "the tile names a folder that is gone")

    def test_tp29_a_file_preview_is_kept_in_the_users_cache(self):
        cache = texture_library.ThumbnailCache(size=64)
        self.assertTrue(os.path.realpath(cache.cache_dir).startswith(
            os.path.realpath(hostos.cache_root())), cache.cache_dir)
        broken = test_support.put(self.dir, "user/broken.exr", b"no picture")
        cache.remember_failure(broken)
        self.assertTrue(cache.known_failure(broken), "a file that cannot be read is tried again")
        cache.invalidate(broken)    # Render Image
        self.assertFalse(cache.known_failure(broken), "Render Image did not try it again")
        cache.remember_failure(broken)
        test_support.put(self.dir, "user/broken.exr", b"a file that changed since")
        self.assertFalse(cache.known_failure(broken), "a changed file is not tried again")


if __name__ == "__main__":
    unittest.main()
