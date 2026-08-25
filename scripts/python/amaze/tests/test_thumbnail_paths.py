"""Renderer and thumbnail paths; several read the SOURCE, because every copy behaves correctly until one drifts."""

import ast
import inspect
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import scene_captures, thumbnails, tile_icons  # noqa: E402
from amaze.core import library as library_mod  # noqa: E402
from amaze.core import texture_library  # noqa: E402
from amaze.helpers import hostos  # noqa: E402
from amaze.render import thumbs  # noqa: E402
from amaze import preview  # noqa: E402
from amaze.tests import test_support  # noqa: E402

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def source_of(relative: str) -> str:
    with open(os.path.join(PACKAGE, relative), encoding="utf-8") as handle:
        return handle.read()


class _Parm:
    def __init__(self, log, name):
        self._log, self._name = log, name

    def set(self, value, **kw):
        self._log.append((self._name, value))

    def pressButton(self):
        self._log.append((self._name, "PRESSED"))


class _Thumb:
    """Stands in for the thumbnail subnet, so the render verdict is answerable without a Scene Viewer or a licence."""

    def __init__(self, missing=()):
        self.sets = []
        self.destroyed = 0
        self.missing = set(missing)

    def parm(self, name):
        return None if name in self.missing else _Parm(self.sets, name)

    def name(self):
        return "Thumbnail_Stub"

    def path(self):
        return "/obj/Thumbnail_Stub"

    def destroy(self):
        self.destroyed += 1


class _Scene:
    def __init__(self, renderer="Redshift", missing=()):
        self.renderer = renderer
        self.thumb = _Thumb(missing)
        self.rop = _Thumb()

    def get_node(self):
        return self.thumb


class _RendererCase(unittest.TestCase):

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.prefs = test_support.fixture_prefs(self)
        self.renderer = thumbs.ThumbNailRenderer(self.prefs)
        self.scenes = []

    def stub_scene(self, missing=()):
        # Patch the PACKAGE name, which thumbs.py resolves at call time.
        real = preview.ThumbNailScene
        self.addCleanup(setattr, preview, "ThumbNailScene", real)

        def factory(renderer="Redshift"):
            scene = _Scene(renderer, missing)
            self.scenes.append(scene)
            return scene

        preview.ThumbNailScene = factory

    def paths(self):
        # Every case walks this tuple, so a dropped renderer goes HERE.
        return (("Redshift", self.renderer.create_thumb_redshift),
                ("Octane", self.renderer.create_thumb_octane))


class ARenderThatWroteNothingReportsFailure(_RendererCase):

    def test_no_image_means_False(self):
        self.stub_scene()
        for name, call in self.paths():
            self.assertFalse(
                call(hou.node("/obj"), "NO_SUCH_ASSET"),
                "%s reported success after a render that wrote no "
                "image - nodes.py's failure branch for it is dead code, "
                "and a failed render keeps the OLD thumbnail, so the "
                "tile shows the previous picture and nothing anywhere "
                "says the new one never happened" % name)

    def test_an_image_that_IS_there_means_True(self):
        """The check must not cost the ordinary case."""
        self.stub_scene()
        for name, call in self.paths():
            target = tile_icons.thumbnail_path(self.prefs, "WROTE_%s" % name)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            QtGui.QImage(4, 4, QtGui.QImage.Format.Format_RGB32).save(target)
            self.assertTrue(
                call(hou.node("/obj"), "WROTE_%s" % name),
                "%s reported failure although the image is on disk" % name)


class EveryRendererCleansUpItsScene(_RendererCase):

    def test_a_missing_parm_still_destroys_the_scene(self):
        """A missing `mat` parm must still leave no Thumbnail_* subnet in the user's scene."""
        for name, call in self.paths():
            self.scenes = []
            self.stub_scene(missing=("mat",))
            try:
                call(hou.node("/obj"), "X")
            except Exception:                             # noqa: BLE001
                pass
            self.assertTrue(self.scenes, "no scene was built for " + name)
            self.assertEqual(
                1, self.scenes[-1].thumb.destroyed,
                "%s did not destroy its thumbnail scene when a parm was "
                "missing - an orphaned subnet with a live ROP is left in "
                "/obj and saved into the user's scene" % name)


class TheThumbnailPathIsComposedInOnePlace(unittest.TestCase):

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.prefs = test_support.fixture_prefs(self)

    def test_the_separator_cannot_change_the_answer(self):
        """A trailing separator on `prefs.dir` may not move the thumbnail path."""
        model = library_mod.MaterialLibrary(preferences=self.prefs)
        root = self.prefs.dir.rstrip(os.sep)

        answers = set()
        for value in (root, root + os.sep):
            self.prefs.dir = value
            answers.add(os.path.normpath(
                model.asset_files("abc")["thumbnail"]))
            answers.add(os.path.normpath(
                tile_icons.thumbnail_path(self.prefs, "abc")))
        self.assertEqual(
            1, len(answers),
            "the renderers and asset_files() resolve a thumbnail to "
            "different places depending on a trailing separator: %s"
            % sorted(answers))

    def test_thumbs_py_composes_no_path_of_its_own(self):
        """thumbs.py composes no library path of its own - a behaviour test cannot see a new hand-built one."""
        offenders = [line.strip() for line in
                     source_of("render/thumbs.py").splitlines()
                     if "_preferences.img_dir" in line]
        self.assertEqual(
            [], offenders,
            "render/thumbs.py composes a thumbnail path by hand again "
            "instead of calling tile_icons.thumbnail_path")

    def test_an_unsafe_id_cannot_escape_the_image_directory(self):
        with self.assertRaises(hostos.PathEscape):
            tile_icons.thumbnail_path(self.prefs, "../../../Documents/x")

    def test_an_unsafe_id_cannot_escape_the_ICON_path_either(self):
        """The icon path refuses an escaping id too - `render_for` writes it and `clear_for` removes it."""
        with self.assertRaises(hostos.PathEscape):
            tile_icons.icon_image_path(self.prefs, "../../../Documents/x")

    def test_the_icon_path_ignores_a_trailing_separator_too(self):
        """The icon path takes a trailing separator the same way its render sibling does."""
        root = self.prefs.dir.rstrip(os.sep)
        answers = set()
        for value in (root, root + os.sep):
            self.prefs.dir = value
            answers.add(os.path.normpath(
                tile_icons.icon_image_path(self.prefs, "abc")))
        self.assertEqual(
            1, len(answers),
            "the composed icon resolves to different places depending "
            "on a trailing separator: %s" % sorted(answers))


class TheCacheKeyCarriesTheLibrary(unittest.TestCase):
    """The RAM cache key carries the library, so two libraries holding one asset id do not share an image."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.prefs = test_support.fixture_prefs(self)

    def test_two_libraries_do_not_share_one_row_key(self):
        model = library_mod.MaterialLibrary(preferences=self.prefs)
        row = next(i for i, a in enumerate(model.assets)
                   if str(a.mat_id) not in ("", "-1"))
        here = model._thumb_key(row)

        self.prefs.dir = os.path.join(
            self.prefs.dir.rstrip("/\\") + "_copy", "")
        there = model._thumb_key(row)

        self.assertNotEqual(
            here, there,
            "the same asset id in two libraries answers one cache key, "
            "so a switch paints the previous library's picture and the "
            "new library's file is never read")

    def test_the_same_library_still_answers_the_same_key(self):
        """A reload must keep the cached image, so the key may not move for one library."""
        model = library_mod.MaterialLibrary(preferences=self.prefs)
        row = next(i for i, a in enumerate(model.assets)
                   if str(a.mat_id) not in ("", "-1"))
        before = model._thumb_key(row)
        root = self.prefs.dir.rstrip("/\\")
        for spelling in (root, root + os.sep):
            self.prefs.dir = spelling
            self.assertEqual(
                before, model._thumb_key(row),
                "a trailing separator moved the key, so an ordinary "
                "reload throws the whole library's cache away")


class TheRenderScratchIsNeverShared(unittest.TestCase):
    """Render scratch names are per item and per process; a shared one caches the previous file's picture against this file's mtime."""

    def test_the_geo_pass_mints_a_scratch_per_item(self):
        source = source_of("core/file_library.py")
        self.assertNotIn(
            '"_render_tmp.png"', source,
            "the geometry pass still shares one fixed scratch name for "
            "every item and every process")
        self.assertIn(
            "hostos.unique_scratch(", source,
            "the geometry pass does not mint a unique scratch")

    def test_the_sop_thumbnail_mints_a_unique_scratch(self):
        source = source_of("render/thumbs.py")
        self.assertNotIn(
            'hostos.cache_root(), "sop_thumb_%s.bgeo" % asset_id\n', source,
            "the SOP thumbnail writes its intermediate geometry to a "
            "fixed name in a directory every Houdini process shares")

    def test_the_render_verdict_reads_a_LIVE_rop(self):
        """The render verdict must read a LIVE ROP: callers ask after the scene block, which has already destroyed it."""
        tree = ast.parse(source_of("render/thumbs.py"))
        rendered = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_rendered")

        inside = [n for n in ast.walk(rendered)
                  if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute)
                  and n.func.attr == "node_errors"]
        self.assertEqual(
            [], inside,
            "_rendered reads the ROP's errors itself, and every caller "
            "invokes it after the scene has been destroyed - so the "
            "field is empty whatever the renderer said")

        args = [a.arg for a in rendered.args.args]
        self.assertIn(
            "errors", args,
            "_rendered does not take the errors its callers gathered "
            "while the scene was alive: %s" % args)
        self.assertNotIn("rop", args)


class ThumbnailsLeaveNothingOnTheUndoStack(unittest.TestCase):
    """A thumbnail leaves nothing on the undo stack, or Ctrl+Z resurrects the scaffold instead of the user's own edit."""

    def test_a_pair_on_the_live_stack_really_does_come_back(self):
        """The measured consequence the source check below is anchored in."""
        def scrub():
            with hou.undos.disabler():
                for child in list(hou.node("/obj").children()):
                    child.destroy()
            hou.undos.clear()

        self.addCleanup(scrub)
        scrub()
        node = hou.node("/obj").createNode("lopnet")
        node.destroy()
        after = {n.path() for n in hou.node("/obj").children()}
        hou.undos.performUndo()
        self.assertTrue(
            {n.path() for n in hou.node("/obj").children()} - after,
            "createNode+destroy on the live stack no longer comes back "
            "on undo - this test's premise is gone, not its subject")

        scrub()
        with hou.undos.disabler():
            guarded = hou.node("/obj").createNode("lopnet")
            guarded.destroy()
        after = {n.path() for n in hou.node("/obj").children()}
        hou.undos.performUndo()
        self.assertFalse(
            {n.path() for n in hou.node("/obj").children()} - after,
            "a disabler no longer keeps the pair off the stack")

    def test_every_scene_container_is_created_off_the_stack(self):
        source = source_of("render/thumbs.py")
        tree = ast.parse(source)
        lines = source.splitlines()
        unguarded = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute)
                    and func.attr == "createNode"):
                continue
            # Scene ROOTS only; a container this code owns is not the user's.
            inner = func.value
            if not (isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "node"
                    and inner.args
                    and isinstance(inner.args[0], ast.Constant)
                    and inner.args[0].value in ("/obj", "/out")):
                continue
            for number in range(node.lineno - 1, max(0, node.lineno - 6), -1):
                text = lines[number - 1]
                if "hou.undos.disabler()" in text:
                    break
                if text.strip().startswith(("def ", "class ")):
                    unguarded.append((node.lineno, lines[node.lineno - 1]
                                      .strip()))
                    break
            else:
                unguarded.append((node.lineno, lines[node.lineno - 1].strip()))
        self.assertEqual(
            [], unguarded,
            "these build a node in the user's /obj or /out on the LIVE "
            "undo stack, so their next Ctrl+Z resurrects a thumbnail "
            "scaffold: %s" % unguarded)

    def test_every_scene_container_is_DESTROYED_off_the_stack(self):
        """A destroy is itself undoable, so a guarded CREATE with a bare DESTROY still hands Ctrl+Z the whole scaffold back."""
        source = source_of("render/thumbs.py")
        tree = ast.parse(source)
        lines = source.splitlines()
        guarded_ranges = [
            (node.lineno, node.end_lineno)
            for node in ast.walk(tree)
            if isinstance(node, ast.With)
            and "disabler" in ast.dump(node.items[0].context_expr)]

        def guarded(lineno):
            return any(first <= lineno <= last
                       for first, last in guarded_ranges)

        unguarded = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "destroy"):
                continue
            if not guarded(node.lineno):
                unguarded.append((node.lineno,
                                  lines[node.lineno - 1].strip()))
        self.assertEqual(
            [], unguarded,
            "these destroy a scene container on the LIVE undo stack, "
            "so one Ctrl+Z resurrects it with its children: %s"
            % unguarded)


class TheSceneBuildKeepsTheUsersSelection(unittest.TestCase):
    """Building a scene puts the user's node selection back; the Redshift spare-parm hscript works on the selection."""

    def test_building_a_redshift_scene_restores_the_selection(self):
        if hou.nodeType(hou.ropNodeTypeCategory(), "Redshift_ROP") is None:
            self.skipTest("Redshift is not available in this session")
        # Patch the SUBMODULE here: the constructor resolves it locally.
        module = preview.thumbnail_scene
        real = module.ocio_from_viewer
        module.ocio_from_viewer = lambda: {
            "display": "sRGB - Display",
            "view": "ACES 1.0 - SDR Video",
            "space": "ACEScg",
        }
        self.addCleanup(setattr, module, "ocio_from_viewer", real)
        with hou.undos.disabler():
            keeper = hou.node("/obj").createNode("null")
        self.addCleanup(lambda: keeper.destroy())
        keeper.setSelected(True, True)
        scene = preview.ThumbNailScene("Redshift")
        try:
            self.assertIn(
                keeper, hou.selectedNodes(),
                "building a thumbnail scene ate the user's selection")
        finally:
            with hou.undos.disabler():
                scene.get_node().destroy()


class _KarmaRopStub:
    """Enough usdrender ROP for the per-material path to be walked with no licence and no Karma cook - `execute` is the only parm `render_karma_into` presses on it."""

    def __init__(self):
        self.pressed = []

    def parm(self, name):
        return _Parm(self.pressed, name)

    def path(self):
        return "/obj/karma_rop_stub"


class AKarmaThumbnailLeavesTheSceneAsItFoundIt(unittest.TestCase):
    """A Karma thumbnail borrows the artist's scene: nothing of its own on their undo stack, their selection back where it was, and the samples preference on the dial the engine it selects actually reads. ▸r/undo-groups"""

    OCIO = {"display": "sRGB - Display", "view": "ACES 1.0 - SDR Video",
            "space": "ACEScg"}

    def setUp(self):
        module = preview.thumbnail_scene    # the SUBMODULE, which karma_scene calls through: headless there is no Scene Viewer to read OCIO from and the build answers None
        real = module.ocio_from_viewer
        module.ocio_from_viewer = lambda: dict(self.OCIO)
        self.addCleanup(setattr, module, "ocio_from_viewer", real)
        self.prefs = test_support.fixture_prefs(self)
        self.out = tempfile.mkdtemp(prefix="amaze_karma_probe_")
        self.addCleanup(shutil.rmtree, self.out, True)
        self.addCleanup(hou.undos.clear)

    @staticmethod
    def _drop(node):
        with hou.undos.disabler():    # the teardown is not the thing under measurement
            try:
                node.destroy()
            except hou.ObjectWasDeleted:
                pass

    def _scaffold(self):
        scaffold = preview.build_karma_scaffold(self.prefs)
        self.assertIsNotNone(
            scaffold,
            "no scaffold was built although the OCIO seam is patched - "
            "this test can no longer see its subject")
        self.addCleanup(self._drop, scaffold["net"])
        scaffold["rop"] = _KarmaRopStub()    # a real `execute` would start a Karma render; every node operation around it stays real
        return scaffold

    def _material(self):
        mat = hou.node("/mat").createNode("subnet", "AmazeKarmaProbe")
        self.addCleanup(self._drop, mat)
        mat.createNode("mtlxstandard_surface")
        return mat

    def test_the_two_sample_dials_belong_to_different_engines(self):
        """The premise the samples check below rests on, asked of the node itself rather than of the manual."""
        render_props = self._scaffold()["render_props"]
        hides = {}
        for name in ("samplesperpixel", "pathtracedsamples"):
            parm = render_props.parm(name)
            self.assertIsNotNone(
                parm, "`karmarenderproperties` no longer carries `%s`" % name)
            hides[name] = parm.parmTemplate().conditionals().get(
                hou.parmCondType.HideWhen, "")
        self.assertIn(
            "engine != cpu", hides["samplesperpixel"],
            "`samplesperpixel` is no longer the CPU-only dial")
        self.assertIn(
            "engine != xpu", hides["pathtracedsamples"],
            "`pathtracedsamples` is no longer the XPU-only dial")

    def test_the_samples_preference_reaches_the_engine_that_renders(self):
        self.prefs.karma_rendersamples = 23    # not 9: the pref default and the parm default are both 9, so an equal pair proves nothing
        render_props = self._scaffold()["render_props"]
        self.assertEqual(
            "cpu", render_props.parm("engine").eval(),
            "the scaffold no longer selects the CPU engine, so which "
            "samples dial it must write is no longer settled")
        self.assertEqual(
            23, render_props.parm("samplesperpixel").eval(),
            "the Karma-samples preference went to the XPU dial, so on "
            "these CPU renders it changes nothing: the artist raises "
            "samples and the thumbnail comes back just as noisy")

    def test_the_scaffold_build_adds_no_undo_entries(self):
        hou.undos.clear()
        self._scaffold()
        self.assertEqual(
            (), hou.undos.undoLabels(),
            "building the scaffold left entries on the live undo stack, "
            "so the artist's next Ctrl+Z undoes thumbnail scaffolding "
            "instead of their own last edit")

    def test_a_render_adds_no_undo_entries(self):
        scaffold = self._scaffold()
        mat = self._material()
        hou.undos.clear()
        preview.render_karma_into(
            scaffold, mat, "UNDO_PROBE", os.path.join(self.out, "u.png"))
        self.assertEqual(
            (), hou.undos.undoLabels(),
            "rendering one material left entries on the live undo "
            "stack; destroying the per-material nodes does not remove "
            "them, so one Ctrl+Z after a thumbnail is spent on noise")

    def test_a_render_puts_the_selection_back(self):
        scaffold = self._scaffold()
        mat = self._material()
        with hou.undos.disabler():
            keeper = hou.node("/obj").createNode("null")
        self.addCleanup(self._drop, keeper)
        keeper.setSelected(True, True)
        preview.render_karma_into(
            scaffold, mat, "SEL_PROBE", os.path.join(self.out, "s.png"))
        self.assertEqual(
            [keeper], list(hou.selectedNodes()),
            "the render ate the artist's selection: `hou.copyNodesTo` "
            "selects the copies it makes, the copies are destroyed at "
            "the end, and nothing puts back what was selected before")


class _CamStub:
    """Enough node for build_cam to run with no licence and no viewer: every parm exists and accepts every set."""

    def __init__(self):
        self.sets = []

    def createNode(self, kind):
        return _CamStub()

    def parm(self, name):
        return _Parm(self.sets, name)

    def setName(self, name, *args):
        pass

    def setInput(self, *args):
        pass

    def setSelected(self, *args):
        pass

    def path(self):
        return "/obj/CamStub"


class TheSpareParmCommandIsCheckedByItsReturnValue(unittest.TestCase):
    """`hou.hscript` reports failure in the SECOND string of the tuple it returns and never raises, so a guard written as `except` alone reads every failure as a success."""

    def _build_cam(self, answer):
        module = preview.thumbnail_scene
        scene = module.ThumbNailScene.__new__(module.ThumbNailScene)
        scene.renderer = "Redshift"
        scene.geo_node = _CamStub()
        scene._user_selection = hou.selectedNodes()   # build_cam puts it back
        asked = []

        def fake_hscript(command):
            asked.append(command)
            return answer

        with mock.patch.object(module.hou, "hscript", fake_hscript), \
                mock.patch.object(module.debug, "event") as recorded:
            scene.build_cam()
        return asked, [call for call in recorded.call_args_list
                       if "Redshift_cameraSpareParameters" in str(call)]

    def test_a_command_that_failed_is_recorded(self):
        asked, said = self._build_cam(
            ("", "Unknown command: RS_camera_spare\n"))
        self.assertEqual(
            1, len(asked),
            "build_cam never ran the spare-parm command, so this test "
            "cannot say anything about how its failure is read")
        self.assertTrue(
            said,
            "the command answered an error and the build recorded "
            "nothing: hou.hscript returns (output, error) and never "
            "raises, so an except clause around it catches nothing and "
            "the failure passes silently")

    def test_a_command_that_worked_is_not_recorded_as_a_failure(self):
        asked, said = self._build_cam(("", ""))
        self.assertEqual(1, len(asked))
        self.assertEqual(
            [], said,
            "an empty error string means the command WORKED - a skip "
            "logged here buries the real ones")


class TheLightRigDegradesLikeTheRopsDo(unittest.TestCase):

    def test_the_light_rig_sets_no_parm_raw(self):
        """Every function that writes a renderer light parm goes through safe_set, so a renamed parm records a skip instead of aborting the thumbnail."""
        source = source_of("preview/thumbnail_scene.py")
        lines = source.splitlines()
        bodies = {
            node.name: lines[node.lineno - 1:node.end_lineno]
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.FunctionDef)
        }
        for name in ("place_light", "build_lights",
                     "build_octane_environment"):
            self.assertIn(
                name, bodies,
                "%s is gone, so this test checks nothing - repoint it at "
                "whatever writes light parms now" % name)
            raw = [line.strip() for line in bodies[name]
                   if ".parm(" in line and ".set(" in line]
            self.assertEqual(
                [], raw,
                "%s sets a version-specific parm without safe_set, which "
                "is the whole reason safe_set is in this file: %s"
                % (name, raw))

    def test_the_shared_rig_numbers_are_written_once(self):
        """The placement both rigs share lives in one constant; two copies is how the light positions drifted apart."""
        source = source_of("preview/thumbnail_scene.py")
        for literal in ("0.182989", "0.400678", "-0.637707", "-164.722",
                        "-11.677", "photo_studio_01_4k_ACEScg.hdr"):
            self.assertEqual(
                1, source.count(literal),
                "%s is written more than once - the values both renderer "
                "rigs share belong in a single constant" % literal)

    def test_a_renderer_with_no_rig_is_refused_not_placed(self):
        """An unnamed renderer raises rather than silently placing a light with no size parms."""
        with self.assertRaises(hou.OperationFailed):
            preview.rig_key("Arnold")

    def test_safe_set_survives_a_missing_parm(self):
        class Bare:
            def parm(self, name):
                return None

            def path(self):
                return "/obj/x"

        preview.safe_set(Bare(), "RSL_intensityMultiplier", 2)


class ParallelConversionsIsALiveCap(unittest.TestCase):

    def test_a_second_dispatch_does_not_double_the_loaders(self):
        """Parallel Conversions caps the LIVE loader count, not each dispatch."""
        engine = thumbnails.ThumbnailEngine()
        engine._convert_parallel = 4
        made = []

        class _Loader:
            def __init__(self, chunk, hfs):
                made.append(self)

            def start(self):
                pass

            def isFinished(self):
                return False

            def isRunning(self):
                return True

            def loaded(self):
                return None

        class Signal:
            def connect(self, *a, **kw):
                pass

        for name in ("loaded", "attempted", "finished"):
            setattr(_Loader, name, Signal())

        real = thumbnails._ConvertLoader
        self.addCleanup(setattr, thumbnails, "_ConvertLoader", real)
        thumbnails._ConvertLoader = _Loader

        engine._convert_queue = [("tex", "/a/%d.exr" % n, 128)
                                 for n in range(20)]
        engine._dispatch_converts()
        first = len(made)
        engine._convert_queue = [("tex", "/b/%d.exr" % n, 128)
                                 for n in range(20)]
        engine._dispatch_converts()

        self.assertEqual(
            first, engine._convert_parallel,
            "the first dispatch did not fill the cap")
        self.assertLessEqual(
            len(made), engine._convert_parallel,
            "a second dispatch started more loaders while %d were still "
            "running - Parallel Conversions caps each dispatch instead "
            "of the live count, so a rerender during a batch doubles the "
            "iconvert processes" % first)


class UpdatePreviewWritesTheManifestOnce(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="amaze_flush_case_")
        self.addCleanup(shutil.rmtree, self.root, True)
        hostos.set_cache_override(self.root)
        self.addCleanup(hostos.set_cache_override, "")

    def test_a_loop_of_invalidates_flushes_once(self):
        writes = []
        real_write = hostos.write_json_atomic
        self.addCleanup(setattr, hostos, "write_json_atomic", real_write)

        cache = texture_library.ThumbnailCache(size=256)
        for n in range(25):
            cache._manifest["/img/%d.png" % n] = {"mtime": 1, "size": 1}
        cache._dirty = True
        cache.save()

        def spy(path, data, **kw):
            writes.append(path)
            return real_write(path, data, **kw)

        hostos.write_json_atomic = spy
        for n in range(25):  # the product's batch spelling (file_library.rerender_thumbnails): per-row evictions, one flush after
            cache.invalidate("/img/%d.png" % n, flush=False)
        cache.save()

        self.assertEqual(
            1, len(writes),
            "25 rows produced %d full manifest serialisations, each with "
            "an fsync and a rename, on the main thread - at 500 selected "
            "images against a manifest measured at 40,000 entries that "
            "is the whole of Update Preview" % len(writes))

    def test_a_file_nothing_can_read_is_not_retried_forever(self):
        """A failed conversion is remembered, keyed to the file's CURRENT mtime and size, so a replaced file converts and Rerender clears it."""
        cache = texture_library.ThumbnailCache(size=256)
        folder = tempfile.mkdtemp(prefix="amaze_failmem_")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        broken = os.path.join(folder, "not_really_a.jpg")
        with open(broken, "wb") as handle:
            handle.write(b"\x00" * 2048)

        self.assertFalse(cache.known_failure(broken),
                         "a file nobody has tried is not a failure")
        cache.remember_failure(broken)
        self.assertTrue(cache.known_failure(broken),
                        "the failure was not remembered, so the file "
                        "is converted again on the next visit")

        cache.invalidate(broken)
        self.assertFalse(cache.known_failure(broken),
                         "Rerender Thumbnail did not clear the memory")

        cache.remember_failure(broken)
        with open(broken, "wb") as handle:
            handle.write(b"\x00" * 4096)
        self.assertFalse(
            cache.known_failure(broken),
            "the memory outlived the file it was about - a fixed "
            "image would never get its thumbnail")

    def test_a_single_invalidate_still_writes(self):
        cache = texture_library.ThumbnailCache(size=256)
        cache._manifest["/img/one.png"] = {"mtime": 1, "size": 1}
        cache._dirty = True
        cache.save()
        cache.invalidate("/img/one.png")
        with open(cache.manifest_path, encoding="utf-8") as handle:
            self.assertNotIn("/img/one.png", json.load(handle),
                             "a one-shot invalidate no longer reaches disk")


class TheCaptureDirectoryIsResolvedOncePerPaint(unittest.TestCase):

    def test_repeated_lookups_stop_running_the_migration(self):
        """The cache-path migration runs once, not per DecorationRole read - the delegate asks on every paint."""
        store = tempfile.mkdtemp(prefix="amaze_capdir_case_")
        self.addCleanup(shutil.rmtree, store, True)
        hostos.set_cache_override(store)
        self.addCleanup(hostos.set_cache_override, "")
        scene_captures.forget_thumb_dir()
        self.addCleanup(scene_captures.forget_thumb_dir)

        calls = {"n": 0}
        real_isdir = os.path.isdir

        def counting(path):
            calls["n"] += 1
            return real_isdir(path)

        scene_captures.thumb_path("/scenes/warm.hip")        # first resolve
        os.path.isdir = counting
        self.addCleanup(setattr, os.path, "isdir", real_isdir)
        try:
            for _ in range(20):
                scene_captures.thumb_path("/scenes/a.hip")
        finally:
            os.path.isdir = real_isdir

        self.assertEqual(
            0, calls["n"],
            "20 paints re-ran the capture directory's migration checks "
            "(%d isdir calls) - it is a once-per-session job"
            % calls["n"])

    def test_a_moved_cache_root_is_still_noticed(self):
        """The memo may not outlive the roots it derives from, or one test's cache directory is handed to the next."""
        first = tempfile.mkdtemp(prefix="amaze_capdir_a_")
        second = tempfile.mkdtemp(prefix="amaze_capdir_b_")
        self.addCleanup(shutil.rmtree, first, True)
        self.addCleanup(shutil.rmtree, second, True)
        self.addCleanup(hostos.set_cache_override, "")
        self.addCleanup(scene_captures.forget_thumb_dir)

        real_config = hostos.config_root
        self.addCleanup(setattr, hostos, "config_root", real_config)

        hostos.config_root = lambda: first
        hostos.set_cache_override(first)
        one = scene_captures.thumb_dir()

        hostos.config_root = lambda: second
        hostos.set_cache_override(second)
        two = scene_captures.thumb_dir()

        self.assertNotEqual(
            one, two,
            "thumb_dir kept the previous root after both roots moved")
        self.assertTrue(two.startswith(second), two)


class ARerenderNeverEntersTheUsersLopContext(unittest.TestCase):

    def test_create_thumbnail_forces_the_mat_context(self):
        """A thumbnail render forces target="mat"; "auto" would import into whatever LOP network the user has in front. Read by AST, not by text. ▸p/source-derived-tests"""
        tree = ast.parse(source_of("render/thumbs.py"))
        targets = []
        for function in ast.walk(tree):
            if not (isinstance(function, ast.FunctionDef)
                    and function.name == "create_thumbnail"):
                continue
            for node in ast.walk(function):
                if not (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "import_asset_to_scene"):
                    continue
                targets.append([kw.value.value for kw in node.keywords
                                if kw.arg == "target"
                                and isinstance(kw.value, ast.Constant)])
        self.assertTrue(
            targets, "create_thumbnail no longer imports an asset at all "
                     "- this test can no longer see its subject")
        self.assertEqual(
            [["mat"]] * len(targets), targets,
            "create_thumbnail imports with the active editor's context "
            "again - a thumbnail has no business in the user's LOP "
            "network, and every rerender there leaves a dead entry "
            "behind and retranslates their whole material library")


class TheDebugBlockCannotChangeTheOutcome(unittest.TestCase):

    def test_render_karma_into_guards_its_index(self):
        """The Debug-gated tier may not change behaviour: an unguarded index inside `if debug.is_on()` fails only for people running with Debug on."""
        tree = ast.parse(source_of("preview/karma_scene.py"))
        checked = False
        for function in ast.walk(tree):
            if not (isinstance(function, ast.FunctionDef)
                    and function.name == "render_karma_into"):
                continue
            for node in ast.walk(function):
                if not (isinstance(node, ast.If)
                        and "is_on" in ast.dump(node.test)):
                    continue
                dumped = ast.dump(ast.Module(body=node.body,
                                             type_ignores=[]))
                if "'curr_nodes'" in dumped and "Subscript" in dumped:
                    checked = True
                    self.assertIn(
                        "IfExp", dumped,
                        "the Debug-Mode block indexes curr_nodes[0] with "
                        "no guard, 40 lines below the identical index "
                        "that has one")
        self.assertTrue(
            checked,
            "no Debug-Mode block indexing curr_nodes was found - this "
            "test can no longer see its subject")


class BothRedshiftTerminalsAreLookedFor(unittest.TestCase):
    """Both Redshift terminal node types are looked for; testing the first literal alone loses displacement on the USD flavour silently."""

    def _sources(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for folder, _dirs, files in os.walk(root):
            if "tests" in folder or "__pycache__" in folder:
                continue
            for name in files:
                if name.endswith(".py"):
                    path = os.path.join(folder, name)
                    with open(path, encoding="utf-8") as handle:
                        yield name, handle.read()

    def test_the_constant_names_both(self):
        from amaze.render import nodes
        self.assertEqual(("redshift_material", "redshift_usd_material"),
                         nodes.REDSHIFT_TERMINALS)

    def test_no_source_compares_against_the_bare_literal(self):
        offenders = []
        for name, source in self._sources():
            if name == "nodes.py":
                continue          # where the constant is defined
            for number, line in enumerate(source.splitlines(), 1):
                if line.strip().startswith("#"):
                    continue
                if '"redshift_material"' not in line:
                    continue
                if "==" in line or "!=" in line:
                    offenders.append("%s:%d" % (name, number))
        self.assertEqual(
            [], offenders,
            "a terminal is matched against one literal, so the USD "
            "flavour is invisible there: %s" % offenders)


class ANodeRefusalIsCaughtAsHouError(unittest.TestCase):
    """Every `createNode` catches `hou.Error`: `PermissionError` is a sibling of `OperationFailed`, so the narrower clause lets a locked-asset refusal through. ▸r/hou-errors"""

    def test_the_hierarchy_is_what_this_rests_on(self):
        self.assertTrue(issubclass(hou.PermissionError, hou.Error))
        self.assertFalse(
            issubclass(hou.PermissionError, hou.OperationFailed),
            "the premise changed - PermissionError is now caught by an "
            "OperationFailed handler and this guard is pointless")

    def test_no_createNode_is_guarded_by_OperationFailed_alone(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        offenders = []
        for folder, _dirs, files in os.walk(root):
            if "tests" in folder or "__pycache__" in folder:
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as handle:
                    lines = handle.read().splitlines()
                for number, line in enumerate(lines):
                    if "except hou.OperationFailed" not in line:
                        continue
                    # Walk back to the `try:` that owns this handler.
                    window = []
                    back = number - 1
                    while back >= 0 and len(window) < 14:
                        window.append(lines[back])
                        if lines[back].strip() == "try:":
                            break
                        back -= 1
                    if any(".createNode(" in w for w in window):
                        offenders.append("%s:%d" % (name, number + 1))
        self.assertEqual(
            [], offenders,
            "a createNode is guarded by OperationFailed alone, so a "
            "locked asset's refusal escapes as a traceback: %s"
            % offenders)


class BundledFilesAreFoundThroughOneLookup(unittest.TestCase):
    """Bundled files resolve through the one lookup; `ui_asset` is the named exception, preferring the INSTALLED copy so a dev tree and $AMAZE cannot disagree. ▸p/adoption"""

    def test_package_file_returns_a_real_bundled_path(self):
        import amaze
        found = amaze.package_file("res", "def", "library.json")
        self.assertTrue(os.path.isabs(found), "not an absolute path")
        self.assertTrue(found.startswith(amaze.PACKAGE_ROOT),
                        "resolved outside the package")
        self.assertTrue(os.path.exists(found),
                        "the starter library is not where this says")

    def test_no_source_file_concatenates_the_install_variable(self):
        """The unsafe join must be unwritable; the concatenation is often on the NEXT line, so this reads the pair."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        offenders = []
        for folder, _dirs, files in os.walk(root):
            if "tests" in folder or "__pycache__" in folder:
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as handle:
                    lines = handle.read().splitlines()
                for number, line in enumerate(lines, 1):
                    if line.strip().startswith("#"):
                        continue
                    if 'getenv("AMAZE")' not in line:
                        continue
                    following = lines[number] if number < len(lines) else ""
                    joined = line + " " + following.strip()
                    if " or " in line.split('getenv("AMAZE")')[-1][:12]:
                        continue
                    if "+" in joined.split('getenv("AMAZE")')[-1]:
                        offenders.append("%s:%d" % (name, number))
        self.assertEqual(
            [], offenders,
            "an install path is glued together with +, so an unset "
            "variable raises TypeError instead of naming a file: %s"
            % offenders)

    MAY_SPELL_THE_INSTALL_JOIN = {"ui_helpers.py"}

    def test_no_bundled_file_is_located_by_rebuilding_the_install_path(self):
        """Any join whose parts spell the install-relative package path is the hand-built lookup, however the root was obtained. ▸p/source-derived-tests"""
        import ast

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        offenders = []
        for folder, _dirs, files in os.walk(root):
            if "tests" in folder or "__pycache__" in folder:
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                if name in self.MAY_SPELL_THE_INSTALL_JOIN:
                    continue
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as handle:
                    tree = ast.parse(handle.read())
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    if not (isinstance(node.func, ast.Attribute)
                            and node.func.attr == "join"):
                        continue
                    parts = " ".join(
                        arg.value for arg in node.args
                        if isinstance(arg, ast.Constant)
                        and isinstance(arg.value, str))
                    if "python" in parts and "amaze" in parts:
                        offenders.append("%s:%d" % (name, node.lineno))
        self.assertEqual(
            [], sorted(offenders),
            "a bundled file is located by rebuilding the install path at "
            "%s - amaze.package_file and ui_helpers.ui_asset are the two "
            "lookups" % ", ".join(sorted(offenders)))

    def test_a_bundled_lookup_survives_an_UNSET_install_variable(self):
        """With $AMAZE unset a bundled lookup still finds the file, or the toolbar icons vanish while the badge SVGs draw."""
        import amaze
        from amaze.core import gradient_library
        from amaze.helpers import ui_helpers

        real = hou.getenv("AMAZE")
        hou.putenv("AMAZE", "")
        self.addCleanup(hou.putenv, "AMAZE", real or "")
        for label, found in (
                ("a bundled resource", amaze.package_file("res", "def",
                                                          "library.json")),
                ("a ui asset", ui_helpers.ui_asset("badge_favourite.svg")),
                ("a curated def", gradient_library._def_path("gradients.json")),
        ):
            self.assertTrue(
                found and os.path.isabs(found),
                "%s cannot be located with $AMAZE unset, so it silently "
                "does not draw" % label)


class MantraIsNotASupportedRenderer(unittest.TestCase):
    """Mantra is not a supported renderer: scanned as a VALUE and an IDENTIFIER across eight modules, since a partial removal still reads as support. ▸p/source-derived-tests"""

    def test_no_source_file_supports_mantra(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        offenders = []
        for folder, _dirs, files in os.walk(root):
            if "tests" in folder or "__pycache__" in folder:
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as handle:
                    lines = handle.read().splitlines()
                # PROSE MAY NAME IT; CODE MAY NOT - hence docstring state.
                in_doc = False
                for number, line in enumerate(lines, 1):
                    bare = line.strip()
                    fences = line.count('"""') + line.count("'''")
                    was_in_doc = in_doc
                    if fences % 2:
                        in_doc = not in_doc
                    if was_in_doc or in_doc or bare.startswith("#"):
                        continue
                    code = line.split("#")[0]
                    if '"Mantra"' in code or "'Mantra'" in code:
                        offenders.append("%s:%d value" % (name, number))
                    elif "mantra" in code.lower():
                        offenders.append("%s:%d name" % (name, number))
        self.assertEqual(
            [], offenders,
            "Mantra was dropped, so a branch or a name that still "
            "carries it is either dead code reading as support or a "
            "control with nothing behind it: %s" % offenders)


class TheAfterSaveThumbnailIsOneBlock(unittest.TestCase):
    """Four copies of the after-save thumbnail block is how two of them lost the traceback the debug log is read for."""

    @staticmethod
    def _scopes_containing(needle):
        source = source_of("render/nodes.py")
        lines = source.splitlines()
        found = []
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.FunctionDef):
                continue
            body = lines[node.lineno - 1:node.end_lineno]
            code = [line.split("#")[0] for line in body]
            if any(needle in line for line in code):
                found.append(node.name)
        return sorted(found)

    def _handler(self, render_on_import=1):
        from amaze.render import nodes

        class _Prefs:
            pass

        prefs = _Prefs()
        prefs.render_on_import = render_on_import
        return nodes, nodes.NodeHandler(prefs)

    def test_one_scope_decides_whether_to_render(self):
        """Every save asks the preference in the same place; four copies is four chances for one to answer differently."""
        scopes = self._scopes_containing("render_on_import")
        self.assertEqual(
            ["after_save_thumbnail"], scopes,
            "the render_on_import decision is written in %d places, so a "
            "save path can drift out of step with the others: %s"
            % (len(scopes), scopes))

    def test_no_save_path_catches_its_own_thumbnail_failure(self):
        """One block catches what the render raises; four catches is how two of them came to record less than the other two."""
        source = source_of("render/nodes.py")
        lines = source.splitlines()
        offenders = []
        for scope in ast.walk(ast.parse(source)):
            if (not isinstance(scope, ast.FunctionDef)
                    or scope.name == "after_save_thumbnail"):
                continue
            for block in ast.walk(scope):
                if not isinstance(block, ast.Try):
                    continue
                body = lines[block.lineno - 1:block.end_lineno]
                code = "\n".join(line.split("#")[0] for line in body)
                if "thumb" in code.lower():
                    offenders.append("%s:%d" % (scope.name, block.lineno))
        self.assertEqual(
            [], offenders,
            "a save path handles its own thumbnail failure instead of "
            "going through the one block: %s" % offenders)

    def test_a_thumbnail_that_raises_is_recorded_with_its_traceback(self):
        """A failure records the traceback AND the asset id and node path, which is what the log is read for."""
        nodes, handler = self._handler()

        def boom():
            raise RuntimeError("no licence")

        with mock.patch.object(nodes.debug, "exception") as caught, \
                mock.patch.object(nodes.debug, "note"):
            handler.after_save_thumbnail(
                False, "Karma", "abc123", "/mat/x", boom)
        self.assertEqual(1, caught.call_count)
        self.assertEqual(
            {"asset_id": "abc123", "node": "/mat/x"}, caught.call_args.kwargs)

    def test_a_thumbnail_that_reports_failure_is_recorded_as_one(self):
        """False means it tried and failed - a structured save record, on every renderer rather than only on Karma."""
        nodes, handler = self._handler()
        with mock.patch.object(nodes.debug, "event") as recorded, \
                mock.patch.object(nodes.debug, "note"):
            handler.after_save_thumbnail(
                False, "Octane", "abc123", "/mat/x", lambda: False)
        self.assertEqual(1, recorded.call_count)
        self.assertEqual("save", recorded.call_args.args[0])

    def test_a_context_with_no_picture_is_not_a_failure(self):
        """render_network_thumbnail answers None where a context has nothing to draw - Lop, Dop - and that must not read as a failed render."""
        nodes, handler = self._handler()
        with mock.patch.object(nodes.debug, "event") as recorded, \
                mock.patch.object(nodes.debug, "exception") as caught, \
                mock.patch.object(nodes.debug, "note") as said:
            handler.after_save_thumbnail(
                False, "Network", "abc123", "/obj/x", lambda: None)
        self.assertEqual(
            (0, 0, 0),
            (recorded.call_count, caught.call_count, said.call_count))

    def test_the_preference_is_honoured_and_an_update_overrides_it(self):
        """Render Thumbs on Import off means no render on a save, and an explicit update re-renders regardless."""
        nodes, handler = self._handler(render_on_import=0)
        ran = []
        handler.after_save_thumbnail(
            False, "Karma", "abc123", "/mat/x", lambda: ran.append("save"))
        handler.after_save_thumbnail(
            True, "Karma", "abc123", "/mat/x", lambda: ran.append("update"))
        self.assertEqual(["update"], ran)

    def test_the_network_save_asks_the_one_context_helper(self):
        """The Cop-or-Sop context read is CopLibrary.context_of; nodes.py hand-rolled the same guarded read beside it."""
        scopes = self._scopes_containing("childTypeCategory")
        self.assertNotIn(
            "save_node_cop", scopes,
            "save_node_cop reads childTypeCategory itself instead of "
            "asking context_of, which answers the same question with the "
            "same guard")


if __name__ == "__main__":
    unittest.main()
