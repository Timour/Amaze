"""The renderer and thumbnail paths: five copies, and the guard that
was in one of them.

BATCH 2's shape, which is not Batch 1's. Nothing here loses data; what
these findings have in common is that a fix landed in ONE of several
copies of the same code, or a check the Karma path has was never given
to its three siblings:

  * Mantra/Redshift/Octane ended with a bare `return True` after
    pressing the render button, so every caller's failure branch in
    nodes.py was unreachable and a render that produced nothing
    reported success;
  * Mantra set its material parm OUTSIDE the try whose finally
    destroys the scene, where its two copies set it inside;
  * the library thumbnail path was hand-concatenated in nine places
    while asset_files() composed it with os.path.join;
  * three of four thumbnail paths built throwaway /obj nodes on the
    live undo stack; only create_thumb_sop disabled undo;
  * build_lights set ~100 version-specific parms raw while the ROPs
    one screen below used safe_set for the identical reason;
  * the big-image rescue never received the `cancelled` callback its
    watchdog is armed by (that one moved to `test_conversion.py` with
    the Conversion Engine, 2026-08-03);
  * Parallel Conversions capped each dispatch rather than the live
    count.

A behaviour test cannot see most of these, because every copy behaves
correctly right up until one drifts - so several of these read the
source, deliberately, the way test_toolbar_filter already does for the
chip art.
"""

import ast
import inspect
import json
import os
import shutil
import sys
import tempfile
import unittest

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


# ------------------------------------------------------------- stubs
class _Parm:
    def __init__(self, log, name):
        self._log, self._name = log, name

    def set(self, value, **kw):
        self._log.append((self._name, value))

    def pressButton(self):
        self._log.append((self._name, "PRESSED"))


class _Thumb:
    """Stands in for the thumbnail subnet: ThumbNailScene needs a live
    Scene Viewer, and hython has none - which is also what makes "did
    it check the render happened" answerable without a licence."""

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
    def __init__(self, renderer="Mantra", missing=()):
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
        # PATCHED ON THE PACKAGE, because that is the name thumbs.py
        # resolves at call time. Patching the submodule instead leaves
        # the stub on a name nobody reads, and only ONE of the tests
        # using this would notice: the two that assert on whether a PNG
        # exists would go on passing while really building Mantra,
        # Redshift and Octane scenes in /obj during the suite.
        real = preview.ThumbNailScene
        self.addCleanup(setattr, preview, "ThumbNailScene", real)

        def factory(renderer="Mantra"):
            scene = _Scene(renderer, missing)
            self.scenes.append(scene)
            return scene

        preview.ThumbNailScene = factory

    def paths(self):
        return (("Mantra", self.renderer.create_thumb_mantra),
                ("Redshift", self.renderer.create_thumb_redshift),
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
        """`thumb.parm("mat")` returning None is the exact case
        thumbnail_scene.safe_set exists for. Mantra set it before its
        try, so the raise escaped the finally and left
        /obj/Thumbnail_Mantra in the user's scene - saved into their
        hip file. Its two copies were protected by one line of
        placement."""
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
        """`dir` is normalised in get_data() alone; the SETTER is not.
        The concatenated form and asset_files() therefore disagreed for
        any path that assigns prefs.dir and renders before a save - the
        render reported success while the tile read Missing Thumbnail
        forever, and an unaccounted PNG was left outside the library."""
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
        """Nine hand-concatenations is how the two forms drifted; a
        behaviour test cannot see a tenth being added."""
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


class ThumbnailsLeaveNothingOnTheUndoStack(unittest.TestCase):
    """research.md ▸ Undo names thumbnail rendering explicitly, and
    create_thumb_sop's own comment says what it costs: "on the stack,
    the user's next Ctrl+Z resurrects a stray /obj/geo full of the
    asset's nodes instead of undoing what they actually did"."""

    def test_a_pair_on_the_live_stack_really_does_come_back(self):
        """The mechanism, so the source check below is anchored in a
        measured consequence rather than a style rule."""
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
            # hou.node("/obj") / hou.node("/out") only - a createNode on
            # a container this code already owns is not on the user's
            # scene root.
            inner = func.value
            if not (isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "node"
                    and inner.args
                    and isinstance(inner.args[0], ast.Constant)
                    and inner.args[0].value in ("/obj", "/out")):
                continue
            # Walk back to the nearest `with` header above it.
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
        """The other half, and the half that actually resurrects: a
        destroy left on the stack is itself undoable (the mechanism
        test above measures it), so a guarded CREATE with a bare
        DESTROY still hands Ctrl+Z the whole scaffold back - reference,
        materiallibrary and live ROP. The Karma scaffold's teardown in
        create_thumb_mtlx was the one destroy in this file outside a
        disabler, among siblings that all state the both-ends rule."""
        source = source_of("render/thumbs.py")
        tree = ast.parse(source)
        lines = source.splitlines()
        # A disabler guards its LEXICAL block, not a line window - the
        # _thumb_scene teardown sits eight lines under its `with` and
        # is fully covered, so this scan reads scope, not proximity.
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
    """The Redshift branch selects the camera and the geo to run the
    spare-parameter hscript, and never put the user's own selection
    back - so saving or re-rendering any Redshift material silently
    wiped whatever nodes they had selected in the network editor."""

    def test_building_a_redshift_scene_restores_the_selection(self):
        if hou.nodeType(hou.ropNodeTypeCategory(), "Redshift_ROP") is None:
            self.skipTest("Redshift is not available in this session")
        # THE SEAM, not a second skip. This test guarded only on
        # Redshift while also needing a GUI, so it errored under H21
        # (no `hou.ui`) and skipped under H22 (no Redshift) - it had
        # never run anywhere. The display and view are the only things
        # the viewer supplies; nothing else here needs one.
        # PATCHED ON THE SUBMODULE, not the package, and the difference
        # is the opposite way round from stub_scene above: this test
        # builds a scene DIRECTLY, and the constructor calls
        # ocio_from_viewer as a module-level name. Patching the package
        # attribute would leave the real one running and the test back
        # to needing a live viewer.
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


class TheLightRigDegradesLikeTheRopsDo(unittest.TestCase):

    def test_build_lights_sets_no_parm_raw(self):
        """safe_set exists in this file "if the renderer version does
        not expose it (parameter names change between Redshift
        releases)", and build_rops uses it for every ROP parm.
        build_lights set ~100 version-specific parms raw - so a renamed
        light parm on a new Redshift/Octane build was an AttributeError
        inside __init__, aborting the thumbnail, where safe_set records
        a skipped parm and carries on."""
        source = source_of("preview/thumbnail_scene.py")
        start = source.index('def build_lights', 0)
        end = source.index('def build_rops', 0)
        raw = [line.strip() for line in source[start:end].splitlines()
               if ".parm(" in line and ".set(" in line]
        self.assertEqual(
            [], raw,
            "build_lights sets a version-specific parm without safe_set, "
            "which is the whole reason safe_set is in this file: %s" % raw)

    def test_safe_set_survives_a_missing_parm(self):
        class Bare:
            def parm(self, name):
                return None

            def path(self):
                return "/obj/x"

        preview.safe_set(Bare(), "RSL_intensityMultiplier", 2)


class ParallelConversionsIsALiveCap(unittest.TestCase):

    def test_a_second_dispatch_does_not_double_the_loaders(self):
        """A folder of 500 EXRs opens and 8 loaders start, each shelling
        out to iconvert. Minutes later the user picks Update Preview:
        this used to start 8 more, against a preference of 8."""
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

        # Signals are attribute lookups here; the engine only connects
        # them, and a plain object with the names is enough.
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
        cache.invalidate_many(["/img/%d.png" % n for n in range(25)])

        self.assertEqual(
            1, len(writes),
            "25 rows produced %d full manifest serialisations, each with "
            "an fsync and a rename, on the main thread - at 500 selected "
            "images against a manifest measured at 40,000 entries that "
            "is the whole of Update Preview" % len(writes))

    def test_a_file_nothing_can_read_is_not_retried_forever(self):
        """Reported live: browsing a folder stalled again and again on
        the same few files. Nothing recorded a FAILURE, so every visit
        re-queued them and paid every converter's timeout afresh - the
        cost is per visit, forever, for a file that will never decode.

        A remembered failure is keyed to the file as it is NOW (mtime
        and size), so replacing the file with a good one converts it,
        and Rerender Thumbnail clears the memory deliberately."""
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

        # Rerender Thumbnail is the deliberate retry.
        cache.invalidate(broken)
        self.assertFalse(cache.known_failure(broken),
                         "Rerender Thumbnail did not clear the memory")

        # A REPLACED file is a different file, whatever it is called.
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
        """data() calls thumb_path on every DecorationRole read and the
        delegate reads it on every paint, so this ran config_root() +
        cache_root() + two isdir checks per visible tile per frame - and
        in the interrupted-migration branch a full listdir per call,
        permanently."""
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
        """The memo may not outlive the thing it derives from: the
        suite points config_root and cache_root at a fresh temp dir per
        test, and a memo keyed on anything narrower hands one test's
        directory to the next."""
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
        """With target="auto" the destination is the user's ACTIVE
        editor, so a rerender with a LOP network in front imported into
        their materiallibrary - and register_in_materiallibrary appends
        an explicit entry when the builder is not covered by the
        wildcard. cleanup() destroys the node and nothing removes the
        entry, leaving an explicit entry naming a node that does not
        exist: the "Ignoring missing explicit primitive" error class
        thumbs.py already names, on every cook from then on."""
        # BY AST, not by searching the text: the first version of this
        # matched the words `target="mat"` in the COMMENT above the
        # call, so it stayed green with the argument deleted. Sabotage
        # caught it, which is the only thing that could have.
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
        """The verbose tier is Debug-Mode gated and must not change
        behaviour (overview.md §4d). This was the one unguarded index
        in the function, inside `if debug.is_on():` - so an empty copy
        raised IndexError for developers and testers, who are exactly
        the people running with Debug on, while the same material
        rendered fine for everyone else."""
        tree = ast.parse(source_of("render/thumbs.py"))
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


if __name__ == "__main__":
    unittest.main()
