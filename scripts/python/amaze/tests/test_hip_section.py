"""The HIP section: scene files, and captured thumbnails. Two rules every other section follows are broken here, both pinned because both are easy to fix back into being wrong. Thumbnails are CAPTURED, never rendered: a scene cannot regenerate its thumbnail - re-rendering means reconstructing the whole scene, and the first real scene tried could not be cooked at all - so a row without a capture simply has no thumbnail and opening a folder must never start a render pass. And the store is NOT mtime-invalidated: a captured view is a hand-framed artifact, not a derived cache, and re-saving the scene must not erase it."""

import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # BEFORE the app exists ▸p/first-app-picks-the-platform
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401
from amaze.core import file_library, scene_captures, thumbnails  # noqa: E402
from amaze.helpers import hostos, ui_helpers  # noqa: E402
from amaze.panel import sections  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401


class _Prefs:
    """Only what the File model's scene rows actually read (hip rows live in FileFiles since the merge)."""

    def __init__(self, folders=(), favorites=(), subfolders=False,
                 dir=""):
        self.dir = dir or tempfile.mkdtemp(prefix="amaze_hip_prefs_")  # tile_icons reads .dir to find the library's icons.json
        self.file_folders = list(folders)
        self.file_favorites = list(favorites)
        self.file_recursive_folders = list(folders) if subfolders else []  # recursion is per LOCATION: the stub's flag marks every registered folder recursive
        self.file_folder_names = {}
        self.last_file_folder = ""
        self.rendersize = 256
        self.icon_line_weight = "template"
        self.texture_parallel_conversions = 1  # the image/geo pipelines' knobs, read at _load even when the folder holds only scenes
        self.geometry_shading_mode = "hiddenlineghost"
        self.geometry_bg = "black"


class _Tmp:
    def __init__(self, testcase):
        self.dir = tempfile.mkdtemp(prefix="amaze_hip_")
        testcase.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def touch(self, name, body="x"):
        path = os.path.join(self.dir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)
        return path


def _real_scene(testcase, name="open.hiplc"):
    """A scene file that actually EXISTS - capture_open_scene refuses a target that is not on disk (an unsaved scene has a path but no file), so tests using a fictional path asserted against a situation that cannot occur."""
    folder = tempfile.mkdtemp(prefix="amaze_scene_")
    testcase.addCleanup(shutil.rmtree, folder, ignore_errors=True)
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("x")
    return path


class ExtensionsAreOneTypeTest(unittest.TestCase):
    """A library holding your .hiplc beside someone else's .hip must show both - nothing may treat the licence flavour as a category."""

    def test_every_scene_extension_and_nothing_else_is_recognised(self):
        for name, scene in (("a.hip", True), ("b.hiplc", True), ("c.hipnc", True),
                            ("D.HIP", True), ("E.HipLC", True), ("a.hda", False),
                            ("b.bgeo", False), ("c.usd", False), ("d.hip.bak", False),
                            ("e.txt", False), ("notahip", False)):
            with self.subTest(name=name):
                self.assertEqual(scene, bool(scene_captures.matched_extension(name)))

    def test_the_listing_shows_all_three_flavours(self):
        """All three scene extensions are ONE kind - and since the merge the listing shows every file, so the geometry decoy is a row too, just not a scene row."""
        tmp = _Tmp(self)
        for name in ("one.hip", "two.hiplc", "three.hipnc", "skip.bgeo"):
            tmp.touch(name)
        model = file_library.FileFiles(_Prefs([tmp.dir]))
        model.set_folder(tmp.dir)
        self.assertEqual(4, model.rowCount(),
                         "the File section no longer lists every file")
        kinds = [model.data(model.index(i, 0), model.KindRole)
                 for i in range(model.rowCount())]
        self.assertEqual(3, kinds.count(file_library.KIND_HIP),
                         "the section did not treat all three scene "
                         "extensions as one type")


class FormatLabelTest(unittest.TestCase):

    def test_the_format_column_is_title_case(self):
        """Hiplc, not HIPLC - a scene extension reads as a word, unlike the .OBJ/.EXR acronyms the other sections shout."""
        tmp = _Tmp(self)
        for name in ("a.hip", "b.hiplc", "c.hipnc"):
            tmp.touch(name)
        model = file_library.FileFiles(_Prefs([tmp.dir]))
        model.set_folder(tmp.dir)
        labels = {
            model.data(model.index(row, 0), model.FormatRole)
            for row in range(model.rowCount())
        }
        self.assertEqual({"Hip", "Hiplc", "Hipnc"}, labels)


class ThumbnailStoreTest(unittest.TestCase):

    def setUp(self):
        self.tmp = _Tmp(self)
        self.scene = self.tmp.touch("scene.hiplc")
        real = scene_captures.thumb_dir
        self.addCleanup(setattr, scene_captures, "thumb_dir", real)
        self.store = os.path.join(self.tmp.dir, "store")
        scene_captures.thumb_dir = lambda: self.store

    def test_the_slot_is_a_hash_of_the_path(self):
        """An external reader - Anchorpoint, say - has to be able to go from a scene path to its image without reading our code."""
        import hashlib
        from amaze.helpers import hostos
        expected = hashlib.sha1(
            hostos.canonical_path_key(self.scene).encode("utf-8")
        ).hexdigest() + ".png"
        self.assertEqual(expected,
                         os.path.basename(scene_captures.thumb_path(self.scene)))
        self.assertNotEqual(scene_captures.thumb_path(self.scene),
                            scene_captures.thumb_path(self.tmp.touch("other.hiplc")))

    def test_only_a_non_empty_file_counts_as_a_thumbnail(self):
        self.assertFalse(scene_captures.has_thumbnail(self.scene))
        os.makedirs(self.store, exist_ok=True)
        open(scene_captures.thumb_path(self.scene), "wb").close()
        self.assertFalse(scene_captures.has_thumbnail(self.scene),
                         "a zero-byte file was reported as a thumbnail")
        with open(scene_captures.thumb_path(self.scene), "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n")
        self.assertTrue(scene_captures.has_thumbnail(self.scene))

    def test_the_thumbnail_survives_the_scene_being_re_saved(self):
        """The rule that separates this from every other section: a ThumbnailCache would drop the entry here, silently destroying a capture the user framed by hand."""
        os.makedirs(self.store, exist_ok=True)
        with open(scene_captures.thumb_path(self.scene), "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n")
        os.utime(self.scene, (1, 1))
        with open(self.scene, "a", encoding="utf-8") as fh:
            fh.write("the scene changed")
        self.assertTrue(
            scene_captures.has_thumbnail(self.scene),
            "re-saving the scene erased a hand-framed capture")


class CaptureRefusesOutLoudTest(unittest.TestCase):
    """Headless has no viewport, so the capture cannot succeed here - which makes this the right place to pin that it FAILS LOUDLY."""

    def test_no_path_is_refused(self):
        with self.assertRaises(scene_captures.CaptureRefused):
            scene_captures.capture_thumbnail("")

    def test_headless_refusal_names_the_reason(self):
        with self.assertRaises(scene_captures.CaptureRefused) as caught:
            scene_captures.capture_thumbnail("/tmp/nothing.hiplc")
        message = str(caught.exception)
        self.assertTrue(message.strip(), "refused with no reason given")
        self.assertTrue(
            any(word in message.lower()
                for word in ("viewer", "viewport", "husd")),
            "the refusal did not say what was missing: %s" % message)

    def test_a_refusal_is_never_a_quiet_return(self):
        try:
            result = scene_captures.capture_thumbnail("/tmp/nothing.hiplc")
        except scene_captures.CaptureRefused:
            return
        self.fail("capture_thumbnail returned %r instead of refusing"
                  % (result,))


class _FakeViewport:
    def resolutionInPixels(self):
        return (600, 328)

    def name(self):
        return "persp1"

    def camera(self):
        return None


class _FakeViewer:
    def curViewport(self):
        return _FakeViewport()

    def currentHydraRenderer(self):
        return "Houdini GL"


def _two_tone_png_bytes():
    """Real PNG bytes, two colours - so _looks_blank keeps it."""
    from PySide6 import QtGui
    image = QtGui.QImage(4, 4, QtGui.QImage.Format_RGB32)
    image.fill(QtGui.QColor("black"))
    image.setPixelColor(0, 0, QtGui.QColor("white"))
    handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    handle.close()
    image.save(handle.name, "PNG")
    with open(handle.name, "rb") as fh:
        blob = fh.read()
    os.remove(handle.name)
    return blob


class ScratchNameKeepsTheImageFormatTest(unittest.TestCase):
    """The scratch file must keep the REAL extension: Houdini picks the image format from the extension, not from any argument, and an extension it does not know makes it write native PIC2 instead of PNG - QImage cannot read PIC2, so _looks_blank calls the frame blank and the user is told their viewport was one flat colour. Pinned because appending a suffix to the output name is the obvious way to write this, and it shipped that way for four hours."""

    def setUp(self):
        self.tmp = _Tmp(self)
        self.scene = self.tmp.touch("scene.hiplc")
        real_dir = scene_captures.thumb_dir
        self.addCleanup(setattr, scene_captures, "thumb_dir", real_dir)
        self.store = os.path.join(self.tmp.dir, "store")
        scene_captures.thumb_dir = lambda: self.store

        from husd import assetutils
        real_save = assetutils.saveThumbnailFromViewer
        self.addCleanup(
            setattr, assetutils, "saveThumbnailFromViewer", real_save)
        self.png = _two_tone_png_bytes()
        self.asked_for = []

        def record(sceneviewer=None, output="", croptocamera=True,
                   res=(256, 256)):
            self.asked_for.append(output)  # write the bytes whatever the name, so the assertion is about the NAME and not about a save that failed for it
            with open(output, "wb") as fh:
                fh.write(self.png)

        assetutils.saveThumbnailFromViewer = record

    def test_the_scratch_file_is_still_a_png(self):
        scene_captures.capture_thumbnail(self.scene, viewer=_FakeViewer())
        self.assertTrue(self.asked_for, "the flipbook was never called")
        scratch = self.asked_for[0]
        self.assertEqual(
            ".png", os.path.splitext(scratch)[1].lower(),
            "the scratch name is %r - Houdini reads that extension as "
            "the image format and will not write a PNG"
            % os.path.basename(scratch))

    def test_the_scratch_does_not_collide_with_the_real_slot(self):
        scene_captures.capture_thumbnail(self.scene, viewer=_FakeViewer())
        self.assertNotEqual(scene_captures.thumb_path(self.scene),
                            self.asked_for[0],
                            "the capture wrote straight over the live "
                            "thumbnail - the write-aside is gone")

    def test_the_capture_lands_on_the_real_slot(self):
        result = scene_captures.capture_thumbnail(self.scene,
                                               viewer=_FakeViewer())
        self.assertEqual(scene_captures.thumb_path(self.scene), result)
        self.assertTrue(os.path.isfile(result))
        self.assertFalse(os.path.isfile(self.asked_for[0]),
                         "the scratch file was left behind")


class NoAutomaticCaptureTest(unittest.TestCase):
    """A capture must never happen on its own - pinned in the SOURCE because the failure cannot be reproduced in a test: it needs a GUI, a heavy scene, and it ends with Houdini dead. A capture scheduled 1.2s after opening a cloth-sim scene blocked 22 SECONDS on the first file and never returned on the second - 86GB of RAM consumed, Houdini crashed. A capture runs a flipbook, a flipbook forces the scene to COOK, and cooking someone else's scene is work of unbounded size; no delay fixes that, so there is no delay and no automatic capture at all."""

    def _stripped_source(self, filename):
        import tokenize
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "panel", filename)
        with open(path, "rb") as fh:
            toks = list(tokenize.tokenize(fh.readline))
        rows = {}
        for tok in toks:
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            rows.setdefault(tok.start[0], []).append(tok.string)
        out = []
        for _, pieces in sorted(rows.items()):
            line = ""  # a space between two word-ish tokens, or a def and its name fuse and every search below silently matches nothing
            for piece in pieces:
                if line and (line[-1].isalnum() or line[-1] == "_") and \
                        (piece[0].isalnum() or piece[0] == "_"):
                    line += " "
                line += piece
            out.append(line)
        return "\n".join(out)

    def _panel_source(self):
        return self._stripped_source("panel.py")

    def _sections_source(self):
        """open_hip_scene lives on FileSection, so the scans that aim at it read sections.py."""
        return self._stripped_source("sections.py")

    def test_nothing_schedules_a_capture(self):
        """Comments and docstrings are stripped first - the explanation of why this must not exist would otherwise trip the check. Both files: the capture machinery is the panel's, the verbs that could reach it are the sections'."""
        code = self._panel_source() + "\n" + self._sections_source()
        for row in code.splitlines():
            if "capture_hip_thumbnail" in row:
                self.assertNotIn(
                    "singleShot", row,
                    "a capture is being scheduled on a timer: %s" % row)
                self.assertNotIn(
                    "executeDeferred", row,
                    "a capture is being deferred: %s" % row)
        self.assertNotIn(
            "_schedule_hip_autocapture", code,
            "the automatic capture scheduler is back - it crashed "
            "Houdini with an 86GB allocation on 2026-07-29")

    def test_opening_a_scene_does_not_capture(self):
        """open_hip_scene must open the scene and stop there."""
        code = self._sections_source()
        start = code.find("def open_hip_scene")
        self.assertGreater(start, -1, "open_hip_scene is gone - this "
                                      "test is not exercising anything")
        end = code.find("def ", start + 10)
        body = code[start:end if end > 0 else len(code)]
        for verb in ("capture_thumbnail(", "capture_open_scene(",  # the CALLS, not the bare word; a new entry point joins this tuple
                     "_capture_and_report(", "capture_hip_thumbnail("):
            self.assertNotIn(
                verb, body,
                "opening a scene calls %s; it must only open the scene"
                % verb)

    def test_the_scan_can_actually_see_the_panel(self):
        """Guards the guard: an empty read passes every assertion above - each file scan must see the function it is aimed at."""
        panel_code = self._panel_source()
        section_code = self._sections_source()
        self.assertIn("def open_hip_scene", section_code)
        self.assertIn("def capture_hip_thumbnail", panel_code)
        self.assertGreater(len(panel_code), 10000)
        self.assertGreater(len(section_code), 10000)


class PlaceholderTest(unittest.TestCase):
    """A scene with no capture shows a deliberate tile, not a blank: this section can never fill the gap on its own - nothing renders in the background - so the placeholder is the resting state rather than a loading state, and an empty tile would read as broken."""

    def setUp(self):
        self.tmp = _Tmp(self)
        self.scene = self.tmp.touch("uncaptured.hiplc")
        real = scene_captures.thumb_dir
        self.addCleanup(setattr, scene_captures, "thumb_dir", real)
        scene_captures.thumb_dir = lambda: os.path.join(self.tmp.dir, "store")
        ui_helpers.forget_svg_images()
        self.addCleanup(ui_helpers.forget_svg_images)

    def test_an_uncaptured_scene_gets_the_placeholder(self):
        model = file_library.FileFiles(_Prefs([self.tmp.dir]))
        model.set_folder(self.tmp.dir)
        from PySide6 import QtCore as _QtCore
        shown = model.data(model.index(0, 0),
                           _QtCore.Qt.ItemDataRole.DecorationRole)
        self.assertIsNotNone(
            shown, "an un-captured scene showed nothing at all")
        from amaze.core import tile_icons
        self.assertEqual(tile_icons.generic_image("icon_hip"), shown,
                         "an un-captured scene does not show T08's face")

    def test_the_placeholder_asset_exists(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "ui", "icon_hip.svg")
        self.assertTrue(os.path.isfile(path), "ui/icon_hip.svg is missing")

    def test_a_capture_is_served_through_the_shared_engine(self):
        """Guards the guard twice over: returning the placeholder unconditionally would pass the test above while captures were ignored, and the load must go through thumbnails.engine - reading the PNG directly inside data() decodes it on the UI thread on every repaint, with no cache and no eviction. The engine is asynchronous, so this asserts the WIRING rather than racing it: a stub records the request and returns a recognisable image."""
        from amaze.core import thumbnails
        from PySide6 import QtCore as _QtCore, QtGui as _QtGui
        model = file_library.FileFiles(_Prefs([self.tmp.dir]))
        model.set_folder(self.tmp.dir)

        png = scene_captures.thumb_path(self.scene)
        os.makedirs(os.path.dirname(png), exist_ok=True)
        with open(png, "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n")

        asked = []
        sentinel = _QtGui.QImage(4, 4, _QtGui.QImage.Format.Format_ARGB32)
        real = thumbnails.engine.request_file
        self.addCleanup(setattr, thumbnails.engine, "request_file", real)
        thumbnails.engine.request_file = (
            lambda key, path: asked.append((key, path)) or sentinel)

        shown = model.data(model.index(0, 0),
                           _QtCore.Qt.ItemDataRole.DecorationRole)
        self.assertTrue(asked, "the capture was not requested through "
                               "the shared thumbnail engine")
        self.assertEqual(png, asked[0][1])
        self.assertEqual("hip", asked[0][0][0],
                         "the engine key is not namespaced to this "
                         "section, so it could collide with another")
        self.assertIs(shown, sentinel,
                      "the engine's image was not what the tile showed")


class RepaintDoesNotStatTheDiskTest(unittest.TestCase):
    """A repaint must not re-ask the filesystem: `data(DecorationRole)` is what Qt calls for every visible row on every repaint - scroll, hover, resize - and the capture branch stat'd the PNG inside it; cheap on a warm local disk, which is why it never showed, and not cheap on a sleeping external volume, which a registered File location is exactly where one turns up (research.md - Volume mounts on macOS). `thumb_dir()`'s own memo closed the DIRECTORY half of this path; this is the file half. Counted rather than asserted-by-shape: a test that only checked for a `_capture_seen` attribute would pass while `data()` still stat'd beside it."""

    def setUp(self):
        self.tmp = _Tmp(self)
        self.scene = self.tmp.touch("scene.hiplc")
        real = scene_captures.thumb_dir
        self.addCleanup(setattr, scene_captures, "thumb_dir", real)
        scene_captures.thumb_dir = lambda: os.path.join(self.tmp.dir, "store")
        ui_helpers.forget_svg_images()
        self.addCleanup(ui_helpers.forget_svg_images)

    def _stats_of_the_capture(self):
        """Stats aimed at THIS scene's PNG slot - `file_library.os` is the real `os` module, so patching it is process-wide; only calls naming the slot under test are counted, and an unrelated stat somewhere else in the paint cannot inflate or excuse the number."""
        wanted = scene_captures.thumb_path(self.scene)
        calls = []
        real = os.path.isfile

        def counted(path):
            if path == wanted:
                calls.append(path)
            return real(path)

        self.addCleanup(setattr, os.path, "isfile", real)
        os.path.isfile = counted
        return calls

    def _paint(self, model, times=5):
        from PySide6 import QtCore as _QtCore
        for _ in range(times):
            model.data(model.index(0, 0),
                       _QtCore.Qt.ItemDataRole.DecorationRole)

    def test_an_uncaptured_row_stats_once_however_often_it_paints(self):
        model = file_library.FileFiles(_Prefs([self.tmp.dir]))
        model.set_folder(self.tmp.dir)
        calls = self._stats_of_the_capture()
        self._paint(model, times=5)
        self.assertEqual(
            1, len(calls),
            "five repaints of one un-captured scene cost %d stats - a "
            "repaint is re-asking the disk a question this process "
            "already answered" % len(calls))

    def test_a_zero_byte_capture_is_no_capture(self):
        """The tile asks the store's own rule, so an empty file in the slot paints the placeholder."""
        model = file_library.FileFiles(_Prefs([self.tmp.dir]))
        model.set_folder(self.tmp.dir)
        png = scene_captures.thumb_path(self.scene)
        os.makedirs(os.path.dirname(png), exist_ok=True)
        open(png, "wb").close()
        self.assertEqual(
            "", model._capture_png(self.scene),
            "a zero-byte file was handed to the tile as this scene's capture")

    def test_a_landed_capture_forgets_the_remembered_answer(self):
        """The cache may not outlive the fact it caches - without this the optimisation is a bug: capture a scene that was showing the placeholder and the tile keeps showing it, because the model remembers the no-PNG answer forever."""
        model = file_library.FileFiles(_Prefs([self.tmp.dir]))
        model.set_folder(self.tmp.dir)
        self._paint(model, times=2)          # remembers "no capture"

        png = scene_captures.thumb_path(self.scene)
        os.makedirs(os.path.dirname(png), exist_ok=True)
        with open(png, "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n")
        model._on_capture_landed(self.scene)

        self.assertEqual(
            png, model._capture_png(self.scene),
            "the model still says this scene has no capture after one "
            "landed, so the tile keeps painting the placeholder")


class ViewportStateTest(unittest.TestCase):
    """Read the viewport before asking it for a frame: Houdini has no call that copies the displayed image - every route renders - so a capture costs whatever the active Hydra delegate costs, and with a pathtracer that is unbounded; a capture has been seen to block until a Karma render was stopped."""

    def test_only_the_houdini_delegates_are_fast(self):
        for name, fast in (("Houdini VK", True), ("Houdini GL", True), ("houdini vk", True),
                           ("  Houdini VK  ", True), ("Karma CPU", False),
                           ("Karma XPU", False), ("Redshift", False), ("Arnold", False)):
            with self.subTest(name=name):
                self.assertEqual(fast, scene_captures.delegate_is_fast(name))

    def test_an_obj_viewport_is_not_blocked(self):
        """The case that shipped broken: an OBJ viewport is not Hydra-based, so currentHydraRenderer() raises there - the ordinary case, not a warning sign; treating unreadable as slow stopped every OBJ capture while nothing was rendering at all."""
        class _ObjViewport:
            def currentHydraRenderer(self):
                raise AttributeError("no hydra renderer in OBJ")

            def isRendererPaused(self):
                raise AttributeError("no renderer")

        state = scene_captures.viewport_state(_ObjViewport())
        self.assertFalse(
            state["blocking"],
            "an OBJ viewport was blocked from capturing")
        self.assertFalse(state["readable"])

    def test_no_viewer_does_not_block_either(self):
        """Only a delegate POSITIVELY recognised as a renderer stands in the way - everything else proceeds and fails later with its own reason, if it fails at all."""
        state = scene_captures.viewport_state()
        self.assertFalse(state.get("blocking"))

    def test_a_renderer_blocks_and_is_named_and_houdinis_own_does_not(self):
        class _Viewer:
            def __init__(self, renderer, paused):
                self.renderer, self.paused = renderer, paused

            def currentHydraRenderer(self):
                return self.renderer

            def isRendererPaused(self):
                return self.paused

        state = scene_captures.viewport_state(_Viewer("Karma CPU", True))
        self.assertEqual("Karma CPU", state["renderer"])
        self.assertTrue(state["blocking"])
        self.assertTrue(state["readable"])
        self.assertFalse(
            scene_captures.viewport_state(_Viewer("Houdini VK", False))["blocking"])


class SlowCapturePromptTest(unittest.TestCase):
    """What the refusal SAYS and DOES when the viewport is rendering. Was source-derived against panel.py; the policy moved into scene_captures.capture_open_scene (one home, two callers) and every one of these went red on the move - tests pinned to WHERE the code lives rather than to what it does. Behavioural now: capture_open_scene never touches hou.ui, so the real decision runs headless and the assertions are on its actual output."""

    def _patch(self, name, value):
        original = getattr(scene_captures, name)
        setattr(scene_captures, name, value)
        self.addCleanup(setattr, scene_captures, name, original)

    def _blocking(self, debug_on=False):
        """A viewport rendering through Karma, with capture sabotaged so any attempt to proceed fails the test rather than passing it."""
        self.scene = _real_scene(self)
        self._patch("current_scene_path", lambda: self.scene)
        self._patch("viewport_state",
                    lambda *a: {"blocking": True, "renderer": "Karma CPU"})
        self._patch("capture_thumbnail", lambda p, v=None: self.fail(
            "captured through a rendering delegate - the refusal fell "
            "through into an unbounded stall"))
        original = scene_captures.debug.is_on
        scene_captures.debug.is_on = lambda: debug_on
        self.addCleanup(setattr, scene_captures.debug, "is_on", original)

    def test_the_message_does_not_lecture(self):
        """One line - the person reading it knows what renderer they picked, and repeating it back is noise."""
        self._blocking()
        with self.assertRaises(scene_captures.CaptureRefused) as caught:
            scene_captures.capture_open_scene(self.scene)
        message = str(caught.exception)
        self.assertIn("Please stop the viewport render", message)
        self.assertNotIn("The scene view is using", message)
        self.assertNotIn("Karma", message,
                         "the renderer is named back at the user")

    def test_the_renderer_name_is_debug_mode_only(self):
        self._blocking(debug_on=True)
        with self.assertRaises(scene_captures.CaptureRefused) as caught:
            scene_captures.capture_open_scene(self.scene)
        self.assertIn("Detected: Karma CPU", str(caught.exception),
                      "in Debug Mode the delegate is the whole point")

    def test_the_state_is_read_before_capturing(self):
        """Order, measured rather than read: the state must be consulted BEFORE the capture, or reading it cannot avoid the stall."""
        order = []
        self.scene = _real_scene(self)
        self._patch("current_scene_path", lambda: self.scene)
        self._patch("viewport_state",
                    lambda *a: order.append("state") or {"blocking": False})
        self._patch("capture_thumbnail",
                    lambda p, v=None: order.append("capture") or "/tmp/s.png")
        scene_captures.capture_open_scene(self.scene)
        self.assertEqual(["state", "capture"], order)

    def test_it_refuses_rather_than_offering_to_proceed(self):
        """No capture-anyway offer: proceeding was on offer at first, and a capture through a rendering delegate can block indefinitely while the remedy is one click in the viewport. The sabotaged capture_thumbnail in _blocking is what proves it - if the refusal ever falls through, the test fails there."""
        self._blocking()
        with self.assertRaises(scene_captures.CaptureRefused) as caught:
            scene_captures.capture_open_scene(self.scene)
        self.assertNotIn("anyway", str(caught.exception).lower())


class TileCropTest(unittest.TestCase):
    """A wide capture fills the tile and crops, rather than letterboxing into dead bands."""

    def _delegate(self):
        from amaze.panel.delegates import AssetItemDelegate
        return AssetItemDelegate

    def test_a_wide_image_fills_the_square_and_is_cropped(self):
        from PySide6 import QtGui
        wide = QtGui.QImage(400, 100, QtGui.QImage.Format.Format_ARGB32)
        wide.fill(QtGui.QColor("#336699"))
        out = self._delegate()._icon_pixmap(wide, 64, 1.0, cover=True)
        self.assertEqual(64, out.width())
        self.assertEqual(64, out.height(),
                         "the capture did not fill the tile height")

    def test_contain_leaves_the_short_edge_short(self):
        """Guards the guard: if cover and contain produced the same pixmap, the test above would pass while nothing changed."""
        from PySide6 import QtGui
        wide = QtGui.QImage(400, 100, QtGui.QImage.Format.Format_ARGB32)
        wide.fill(QtGui.QColor("#336699"))
        contained = self._delegate()._icon_pixmap(wide, 64, 1.0, cover=False)
        self.assertLess(
            contained.height(), 64,
            "contain mode already fills the height, so cover mode "
            "changes nothing and this section gained no crop")

    def test_the_crop_is_centred(self):
        """An off-centre crop would cut the subject out of every wide capture."""
        from PySide6 import QtGui
        wide = QtGui.QImage(300, 100, QtGui.QImage.Format.Format_ARGB32)
        wide.fill(QtGui.QColor("#000000"))
        for x in range(140, 160):
            for y in range(40, 60):
                wide.setPixelColor(x, y, QtGui.QColor("#ff0000"))
        out = self._delegate()._icon_pixmap(wide, 64, 1.0, cover=True)
        middle = out.toImage().pixelColor(32, 32)
        self.assertEqual(
            (255, 0, 0), (middle.red(), middle.green(), middle.blue()),
            "the centre of the source is not at the centre of the tile")

    def test_only_hip_rows_ask_for_it(self):
        """Crop became PER-ROW with the merge (one delegate serves four kinds): exactly one crop_role wiring in panel.py, and the model answers it True for hip rows alone - every other kind renders square, where a crop is pure risk."""
        code = open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "panel", "panel.py"), encoding="utf-8").read()
        self.assertEqual(
            1, code.count("crop_role="),
            "crop_role is wired somewhere new; cropping belongs to the "
            "File delegate alone")
        model = file_library.FileFiles(_Prefs())
        model._files = [("/tmp", "a.hip"), ("/tmp", "b.png"),
                        ("/tmp", "c.obj"), ("/tmp", "d.txt")]
        model._kinds = [file_library.kind_for(n)
                        for _f, n in model._files]
        crops = [bool(model.data(model.index(i, 0), model.CropRole))
                 for i in range(4)]
        self.assertEqual([True, False, False, False], crops,
                         "a non-scene kind crops (or the scene kind "
                         "stopped cropping)")


class OpenSceneBadgeTest(unittest.TestCase):
    """The tile of the scene on screen carries a marker."""

    def setUp(self):
        self.tmp = _Tmp(self)
        self.a = self.tmp.touch("a.hiplc")
        self.b = self.tmp.touch("b.hiplc")
        self.model = file_library.FileFiles(_Prefs([self.tmp.dir]))
        self.model.set_folder(self.tmp.dir)
        real = scene_captures.current_scene_path
        self.addCleanup(setattr, scene_captures, "current_scene_path", real)

    def _flags(self):
        return [
            self.model.data(self.model.index(row, 0),
                            self.model.OpenSceneRole)
            for row in range(self.model.rowCount())
        ]

    def test_exactly_the_open_scene_is_marked(self):
        from amaze.helpers import hostos
        scene_captures.current_scene_path = \
            lambda: hostos.canonical_path_key(self.a)
        self.assertEqual([True, False], self._flags())

    def test_nothing_is_marked_when_no_scene_matches(self):
        scene_captures.current_scene_path = lambda: "/tmp/elsewhere.hiplc"
        self.assertEqual([False, False], self._flags())

    def test_the_badge_follows_the_LIVE_scene_not_what_amaze_opened(self):
        """A scene opened by File > Open still gets the badge: the mark answers whether this is the one on screen, which has one true answer regardless of who opened it."""
        from amaze.helpers import hostos
        scene_captures.current_scene_path = \
            lambda: hostos.canonical_path_key(self.b)
        self.assertEqual([False, True], self._flags())


class IconAssetsTest(unittest.TestCase):
    """The icons are looked up by filename at paint time, so a missing or renamed file is a silent no-badge rather than an error."""

    def _ui(self, name):
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "ui", name)

    def test_the_shipped_icons_exist(self):
        for name in ("badge_open.svg", "badge_favourite.svg",  # a missing badge paints nothing
                     "badge_versions.svg", "badge_comment.svg",
                     "badge_execute.svg", "badge_edit.svg",
                     "icon_screenshot.svg", "logo.svg"):
            self.assertTrue(os.path.isfile(self._ui(name)),
                            "ui/%s is missing" % name)

    BUTTON_ICONS = ("icon_library.svg", "icon_renderer.svg",  # consumed by IconMenuButton/ChipToggleButton, which generate hover and pressed themselves
                    "icon_view.svg", "icon_screenshot.svg",
                    "grid.svg", "list.svg", "favourite.svg", "favourite_on.svg")

    def test_button_icons_ship_one_state_only(self):
        """A toolbar icon carries BARE artwork - no ids, no state layers: design exports draw hover and pressed as extra layers, and unhidden they render stacked on the base icon, which is how the capture button shipped with a click rectangle and a download circle drawn over it; the button classes produce those states at runtime, so the asset must carry exactly one. Measured, not invented: every other button icon in ui/ already has zero ids and zero hidden elements."""
        import re
        for name in self.BUTTON_ICONS:
            path = self._ui(name)
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8") as fh:
                body = fh.read()
            self.assertEqual(
                0, body.count('visibility="hidden"'),
                "%s ships hidden state layers - either they render "
                "stacked, or they are dead weight" % name)
            self.assertEqual(
                [], re.findall(r'\bid="', body),
                "%s carries element ids; the shipped button icons have "
                "none, and their presence means a design export went in "
                "unedited" % name)

    def test_button_icons_fill_their_frame_like_the_others(self):
        """A toolbar icon must be the same optical size as its neighbours: the design files use different canvases, so an asset dropped in at its export viewBox can render correctly and still look wrong - a disc at 54% of its canvas next to a gear at 81% appears visibly smaller in the same 30px button; the fix is tightening the viewBox to the artwork, and this pins that it stayed tightened. Measured as INK EXTENT, the thing the eye actually compares - not the viewBox, which says nothing on its own."""
        from PySide6 import QtGui, QtSvg
        extents = {}
        for name in self.BUTTON_ICONS:
            path = self._ui(name)
            if not os.path.isfile(path):
                continue
            renderer = QtSvg.QSvgRenderer(path)
            if not renderer.isValid():
                continue
            side = 100
            image = QtGui.QImage(
                side, side, QtGui.QImage.Format.Format_ARGB32)
            image.fill(0)
            painter = QtGui.QPainter(image)
            renderer.render(painter)
            painter.end()
            xs = [x for y in range(side) for x in range(side)
                  if (image.pixel(x, y) >> 24) & 0xFF > 8]
            if not xs:
                continue
            extents[name] = (max(xs) - min(xs) + 1) / float(side)
        self.assertGreaterEqual(
            len(extents), 6,
            "measured almost nothing - this check is vacuous")
        for name, fill in extents.items():
            self.assertGreater(
                fill, 0.70,
                "%s ink spans only %.0f%% of its frame; the other "
                "toolbar icons span 80-90%%, so it renders visibly "
                "smaller in the same button. Tighten its viewBox to "
                "the artwork." % (name, fill * 100))

    def test_the_scan_covers_icons_that_exist(self):
        """Guards the guard: a renamed asset would make every assertion above vacuous."""
        present = [n for n in self.BUTTON_ICONS
                   if os.path.isfile(self._ui(n))]
        self.assertGreaterEqual(
            len(present), 6,
            "only %d of the listed button icons exist - the convention "
            "check is inspecting almost nothing" % len(present))

    def test_the_badge_family_shares_a_dark_backdrop(self):
        """What makes the four badges a family, stated so a REDRAW does not break it: the art moved twice in one day and both times a test that named hexes went red while the badges were perfectly fine, so this names none. The contract that matters on a tile: all four share a colour (the common backdrop that makes them one set), that shared colour is DARK (a light backdrop disappears on a bright thumbnail), and each badge draws in at least two colours (a mark ON the backdrop, not a flat shape). An export that drops the backdrop, inverts it, or ships a single flat colour fails; a recolour does not."""
        palettes = {name: test_support.art_colours(name)
                    for name in test_support.BADGE_FAMILY}
        shared = set.intersection(*palettes.values())
        self.assertTrue(
            shared,
            "the four badges share no colour at all, so they are not "
            "one family any more: %s" % palettes)
        darkest = min(shared, key=self._svg_luminance)
        self.assertLess(
            self._svg_luminance(darkest), 0.4,
            "the shared backdrop is light (%s) - badges have to read "
            "on a white thumbnail too" % darkest)
        for name, colours in palettes.items():
            self.assertGreaterEqual(
                len(colours), 2,
                "ui/%s.svg draws in one colour - a badge is a mark ON "
                "a backdrop, and this one lost one of the two" % name)

    @staticmethod
    def _svg_luminance(hex_colour: str) -> float:
        """0 (black) to 1 (white), perceptual weights."""
        value = hex_colour.lstrip("#")
        if len(value) == 3:
            value = "".join(c * 2 for c in value)
        r, g, b = (int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    def test_a_button_badge_is_one_art_at_two_strengths(self):
        """Every rest art is drawn at the rest strength, and the hover strength reaches all of it."""
        from amaze import amazetheme
        from amaze.helpers import ui_helpers
        from amaze.panel import delegates
        arts = sorted({b.off_art for b in delegates.BADGES if b.off_art}
                      | {b.art for b in delegates.BADGES if b.dims})
        self.assertEqual(["badge_comment", "badge_comment_off", "badge_edit",
                          "badge_favourite_off", "badge_versions"], arts)
        for art in arts:
            self.assertTrue(self._paths(art + ".svg"), "%s draws nothing" % art)
            with open(self._ui(art + ".svg"), encoding="utf-8") as fh:
                text = fh.read()
            drawn = {float(v) for _k, v in re.findall(
                r'((?:fill|stroke)-opacity)[=:]"?([0-9.]+)', text)}
            self.assertEqual({amazetheme.BADGE_REST_OPACITY}, drawn,    # exported from the rest frames
                             "%s is not drawn at the rest strength the code paints" % art)
            rest = ui_helpers.at_opacity(text, amazetheme.BADGE_REST_OPACITY)
            hover = ui_helpers.at_opacity(text, amazetheme.BADGE_HOVER_OPACITY)
            self.assertNotEqual(self._paint_of(rest), self._paint_of(hover),
                                "%s looks the same at rest and under the pointer" % art)
            alphas = {float(v) for _k, v in re.findall(
                r'((?:fill|stroke)-opacity)[=:]"?([0-9.]+)', hover)}
            self.assertEqual({amazetheme.BADGE_HOVER_OPACITY}, alphas,
                             "%s keeps a part the hover strength does not reach" % art)
        self.assertTrue(self._paths("badge_favourite.svg"),
                        "the favourite state draws nothing")

    def test_a_hover_art_keeps_the_ground_and_colours_the_icon(self):
        """Under the pointer the ground stays at the rest strength and the icon takes its colour."""
        from amaze import amazetheme
        from amaze.panel import delegates
        pairs = [(b.off_art, b.off_hover_art) for b in delegates.BADGES if b.off_hover_art]
        pairs += [(b.art, b.hover_art) for b in delegates.BADGES if b.dims and b.hover_art]
        self.assertEqual(4, len(pairs), "the four button badges do not all colour on hover")
        for rest, hover in pairs:
            with open(self._ui(hover + ".svg"), encoding="utf-8") as fh:
                text = fh.read()
            ground = re.search(r'<path[^>]*?id="Rounded-Rectangle[^"]*"[^>]*?>', text, re.S)
            self.assertIsNotNone(ground, "%s has no ground" % hover)
            self.assertEqual(("#000000", amazetheme.BADGE_REST_OPACITY),
                             self._effective_paint(ground.group(0)),
                             "%s changed its ground" % hover)
            inks = {ink.upper() for ink in re.findall(r'stroke="(#[0-9A-Fa-f]{6})"', text)}
            self.assertTrue(inks, "%s draws no icon" % hover)
            self.assertNotIn("#FFFFFF", inks, "%s keeps %s's white icon" % (hover, rest))

    def test_the_run_button_keeps_its_shape_and_changes_its_paint(self):
        """Rest, hover and press draw one play mark; only the disc's colour answers. ▸r/tile-from-frame"""
        rest = self._paths("badge_execute.svg")
        self.assertTrue(rest, "the run button draws nothing")
        for state in ("badge_execute_hover.svg", "badge_execute_press.svg"):
            drawn = self._paths(state)
            self.assertEqual(len(rest), len(drawn),
                             "%s draws a different number of parts" % state)
            self.assertEqual(rest[-1], drawn[-1],
                             "%s changed the play mark's shape" % state)
        paints = {self._paint(name).__repr__() for name in (
            "badge_execute.svg", "badge_execute_hover.svg", "badge_execute_press.svg")}
        self.assertEqual(3, len(paints), "two of the run button's states look the same")

    @staticmethod
    def _effective_paint(tag):
        """The fill and fill-opacity that actually PAINT a tag: a style attribute outranks the presentation attributes beside it. ▸r/svg-style-wins"""
        def attribute(name):
            found = re.search(r'\b%s="([^"]*)"' % name, tag)
            return found.group(1) if found else None
        style = attribute("style") or ""
        fill = re.search(r'fill:\s*(#[0-9a-fA-F]{6})', style)
        opacity = re.search(r'fill-opacity:\s*([0-9.]+)', style)
        colour = (fill.group(1) if fill else attribute("fill")) or ""
        alpha = opacity.group(1) if opacity else (
            attribute("fill-opacity") or "1")
        return colour.lower(), float(alpha)

    def test_the_badge_backdrop_is_the_one_the_DESIGN_ships(self):
        """The badge art is delivered art, not a code decision: a parallel session once recoloured every backdrop in the working tree unasked - the luminance test above caught the light one, but a DARK wrong colour would have passed it, so this pins the actual value: the design's backdrop is black, identical across the family. If the design genuinely changes, this test changes WITH the art, in the same commit, from the delivered file - an art change becomes a deliberate, reviewed act instead of a silent edit nobody notices until a badge disappears on a white thumbnail."""
        expected_alpha = {"badge_open": 0.75, "badge_favourite": 0.75,    # as drawn; the button
                          "badge_versions": 0.75, "badge_comment": 0.75,    # arts' own value is
                          "badge_favourite_off": 0.75, "badge_edit": 0.75,    # replaced when painted
                          "badge_comment_off": 0.75}
        backdrops = {}
        for name in expected_alpha:
            with open(self._ui(name + ".svg"), encoding="utf-8") as fh:
                body = fh.read()
            match = re.search(
                r'<path[^>]*?id="Rounded-Rectangle[^"]*"[^>]*?>',
                body, re.S)
            self.assertIsNotNone(
                match, "ui/%s.svg has no backdrop shaped like the "
                       "family's" % name)
            backdrops[name] = self._effective_paint(match.group(0))

        colours = {c for c, _o in backdrops.values()}
        self.assertEqual(
            {"#000000"}, colours,
            "a badge backdrop is not the delivered black - the art "
            "was recoloured somewhere other than the design: %s"
            % backdrops)

        for name, want in expected_alpha.items():
            self.assertAlmostEqual(
                want, backdrops[name][1], places=2,
                msg="ui/%s.svg's backdrop opacity left the delivered "
                    "design" % name)

    def _paths(self, name):
        """The drawn geometry of an SVG: every path's `d`, in order."""
        with open(self._ui(name), encoding="utf-8") as fh:
            return re.findall(r'\sd="([^"]+)"', fh.read())

    def _paint(self, name):
        """How that geometry is PAINTED: fills, strokes, opacities and style attributes, in order - deliberately not a colour set, because the hover state's difference has been an opacity and could as easily become a colour next time. Style attributes carry paint too, and outrank the plain ones beside them. ▸r/svg-style-wins"""
        with open(self._ui(name), encoding="utf-8") as fh:
            return self._paint_of(fh.read())

    @staticmethod
    def _paint_of(text):
        return re.findall(r'((?:fill|stroke)(?:-opacity)?|opacity|style)="([^"]+)"', text)


class CaptureButtonTest(unittest.TestCase):
    """The capture button's place in the toolbar, on a REAL panel. These five were source-derived, on the claim that a headless test cannot build the panel - false, tests/ui_snapshot.py has built it headlessly all along - and every one could pass while the row was wrong, because what they matched was text in panel.py: source offsets cannot see the order the builders RUN in, the mirror's reversal, or the two amendments after it, and one assertion was satisfied by a comment. Now the row is READ off the constructed layout, so each fails when the thing it claims to check is broken."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(
            test_support.class_scope(cls))
        cls.section_at_construction = cls.panel.current_section  # recorded before any test drives a tab switch: starts-hidden is a fact about construction, and the tests below change visibility on purpose
        cls.hidden_at_construction = cls.panel.btn_hip_capture.isHidden()

    def _row(self):
        return test_support.toolbar_row(self.panel)

    def test_it_starts_hidden(self):
        """Whichever section opens first is not HIP, and a button that acts on the open scene has no meaning there."""
        self.assertNotEqual(
            "hip", self.section_at_construction,
            "the panel opened ON the HIP section, so this test is not "
            "checking what it was written for")
        self.assertTrue(
            self.hidden_at_construction,
            "the capture button is visible on a freshly built panel, so "
            "it shows in whichever section happens to open first")

    def test_the_button_is_file_only(self):
        """Driven through the real tab switch, both ways - matching the visibility LINE in panel.py proves nothing about whether anything calls it. The File section owns the capture button since the merge."""
        self.panel._on_tab_toggled("file", True)
        self.assertFalse(
            self.panel.btn_hip_capture.isHidden(),
            "the capture button does not appear in the File section")
        self.panel._on_tab_toggled("code", True)
        self.assertTrue(
            self.panel.btn_hip_capture.isHidden(),
            "the capture button stays visible after leaving File")

    def test_the_whole_row_reads_in_the_designed_order(self):
        """One assertion over the entire row, so a control appended, inserted or dropped ANYWHERE shows up - not only in the one builder a source-scoped test happened to name. The order below is the DESIGN (Categories leads, the gear far right with Capture immediately left of it, the stretch holding them at the edge), so it changes when the design does - in the same commit, like the badge art pins. EVERY ENTRY IS A DISTINCT NAME, which is the whole point: while three buttons answered IconMenuButton they were interchangeable, and swapping two of them - a real change to the row the user sees - kept all 763 tests green; they carry objectNames now."""
        row = [entry for entry in self._row() if entry != "gap"]
        self.assertEqual(
            len(set(row)), len(row),
            "two toolbar items share a name, so this assertion cannot "
            "tell them apart and a swap between them would pass - %s"
            % (row,))
        self.assertEqual(
            ["btn_categories", "btn_menu_view", "btn_menu_filter",
             "btn_online", "btn_notes", "cb_viewmode", "cb_favsonly",
             "click_slider", "filter_label", "line_filter", "stretch",
             "btn_hip_capture", "btn_prefs"],
            row,
            "the toolbar row is not in the designed order")


class SectionRegistrationTest(unittest.TestCase):
    """Scene rows live in the File section since the merge - the registration pins move with them."""

    def test_the_file_section_is_registered(self):
        keys = [cls.key for cls in sections.SECTION_CLASSES]
        self.assertIn("file", keys)
        self.assertNotIn("hip", keys,
                         "the HIP tab is back beside the File section "
                         "that absorbed it")

    def test_it_points_at_models_the_panel_builds(self):
        """Every attribute name here is looked up on the panel at runtime, so a typo is invisible until the tab is clicked."""
        file_cls = [c for c in sections.SECTION_CLASSES
                    if c.key == "file"][0]
        for attr in ("files_proxy_attr", "selection_attr", "delegate_attr",
                     "folders_attr", "files_attr"):
            name = getattr(file_cls, attr)
            self.assertTrue(name, "%s is empty" % attr)
            self.assertTrue(name.startswith("file_"),
                            "%s = %r does not name a file model"
                            % (attr, name))

    def test_its_prefs_keys_exist_on_the_real_preferences(self):
        from amaze.prefs import prefs as prefs_module
        file_cls = [c for c in sections.SECTION_CLASSES
                    if c.key == "file"][0]
        real = prefs_module.Prefs()
        for attr in (file_cls.last_folder_pref,):
            self.assertTrue(
                hasattr(real, attr),
                "Preferences has no %r - the section would raise the "
                "moment its tab is opened" % attr)


class CaptureDecisionPathTest(unittest.TestCase):
    """capture_open_scene owns every refusal, so the panel button and the shelf tool cannot drift - and it never touches hou.ui, which is what lets these run headless at all."""

    def _patch(self, name, value):
        original = getattr(scene_captures, name)
        setattr(scene_captures, name, value)
        self.addCleanup(setattr, scene_captures, name, original)

    def test_no_open_scene_is_refused_with_a_reason(self):
        self._patch("current_scene_path", lambda: "")
        with self.assertRaises(scene_captures.CaptureRefused) as caught:
            scene_captures.capture_open_scene()
        self.assertIn("nothing to capture", str(caught.exception).lower())

    def test_a_target_that_is_not_open_is_refused(self):
        self.scene = _real_scene(self)
        self._patch("current_scene_path", lambda: self.scene)
        with self.assertRaises(scene_captures.CaptureRefused) as caught:
            scene_captures.capture_open_scene(_real_scene(self, "other.hiplc"))
        self.assertIn("different scene", str(caught.exception))

    def test_a_rendering_viewport_is_refused(self):
        self.scene = _real_scene(self)
        self._patch("current_scene_path", lambda: self.scene)
        self._patch("viewport_state",
                    lambda *a: {"blocking": True, "renderer": "Karma CPU"})
        self._patch("capture_thumbnail",
                    lambda p, v=None: self.fail("captured through a renderer"))
        with self.assertRaises(scene_captures.CaptureRefused) as caught:
            scene_captures.capture_open_scene(self.scene)
        self.assertIn("stop the viewport render", str(caught.exception))

    def test_the_guard_and_the_capture_get_the_SAME_viewport(self):
        """Resolved once, threaded through: scene_viewer()'s first rung is under-the-cursor, so resolving separately meant moving the mouse between the two calls was enough - the guard cleared on the GL viewport and the flipbook ran on the Karma one, the unbounded block the guard exists to prevent. Each call here returns a DIFFERENT object, so a second resolution cannot go unnoticed."""
        handed = []
        viewers = iter(["FIRST", "SECOND", "THIRD"])
        self.scene = _real_scene(self)
        self._patch("current_scene_path", lambda: self.scene)
        self._patch("scene_viewer", lambda: next(viewers))
        self._patch("viewport_state",
                    lambda v=None: handed.append(("guard", v))
                    or {"blocking": False})
        self._patch("capture_thumbnail",
                    lambda p, v=None: handed.append(("shot", v)) or "/tmp/s.png")
        scene_captures.capture_open_scene(self.scene)
        self.assertEqual(2, len(handed), "guard or capture did not run")
        self.assertEqual(
            handed[0][1], handed[1][1],
            "the guard read %r and the capture shot %r - a second "
            "resolution can pick a different viewport"
            % (handed[0][1], handed[1][1]))
        self.assertIsNotNone(handed[1][1],
                             "the capture resolved its own viewer")

    def test_the_shelf_tool_path_needs_no_target_and_no_amaze_open(self):
        """No tile means no mismatch is possible, so the shelf tool captures whatever is open - including a scene Amaze did not open itself."""
        taken = []
        self.scene = _real_scene(self, "manual.hiplc")
        self._patch("current_scene_path", lambda: self.scene)
        self._patch("viewport_state", lambda *a: {"blocking": False})
        self._patch("capture_thumbnail",
                    lambda p, v=None: taken.append(p) or "/tmp/shot.png")
        out = scene_captures.capture_open_scene()
        self.assertEqual([self.scene], taken)
        self.assertEqual("/tmp/shot.png", out)

    def test_no_panel_entry_point_re_decides(self):
        """Source-derived: EVERY capture entry point must delegate. The first version read only the right-click handler while the toolbar button was a separate method carrying its own copy of the policy and its own wording - the test written to prevent that drift never looked at the method that had it."""
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "panel", "panel.py")
        with open(path, encoding="utf-8") as handle:
            code = handle.read()
        for name in ("capture_hip_thumbnail", "capture_open_scene_thumbnail"):
            start = code.find("def %s" % name)
            self.assertGreater(start, -1, "%s is gone" % name)
            end = code.find("\n    def ", start + 10)
            body = re.sub(r"#.*", "", code[start:end if end > 0 else len(code)])
            self.assertIn(
                "_capture_and_report", body,
                "%s does not use the shared path" % name)
            for owned in ("viewport_state(", "displayMessage("):
                self.assertNotIn(
                    owned, body,
                    "%s re-decides with %s - that belongs to "
                    "capture_open_scene, once" % (name, owned))

class CaptureRefreshesTheTileTest(unittest.TestCase):
    """Regression: the shelf tool captured correctly - the PNG replaced each time - and the tile did not change. The engine keeps a decoded copy in memory and nothing invalidated it, because the REFRESH lived in the panel button right after its own call rather than in the capture; one caller hid that, a second exposed it immediately."""

    def test_the_whole_chain_repaints_the_right_row(self):
        """END TO END: emit -> slot -> row_for_path -> refresh_row. The original three cases tested the links and never the chain, so replacing _on_capture_landed's body with a bare return left them all green - the regression this class is named for, twice shipped. The case this replaces emitted the signal itself after connecting its own listener, which tested PySide rather than Amaze."""
        tmp = _Tmp(self)
        scene = tmp.touch("one.hiplc")
        tmp.touch("two.hiplc")
        model = file_library.FileFiles(_Prefs([tmp.dir]))
        model.set_folder(tmp.dir)
        dropped, painted = [], []
        original = thumbnails.engine.discard
        thumbnails.engine.discard = dropped.append
        self.addCleanup(setattr, thumbnails.engine, "discard", original)
        model.dataChanged.connect(
            lambda tl, br, roles=None: painted.append(tl.row()))

        scene_captures.signals.captured.emit(scene)

        self.assertEqual(
            [model.row_for_path(scene)], painted,
            "the capture did not repaint the row for the captured scene")
        self.assertEqual(1, len(dropped),
                         "the engine's stale copy was not dropped")

    def test_an_unrelated_scene_does_not_repaint_anything(self):
        """The slot must find the RIGHT row, not merely any row."""
        tmp = _Tmp(self)
        tmp.touch("one.hiplc")
        model = file_library.FileFiles(_Prefs([tmp.dir]))
        model.set_folder(tmp.dir)
        painted = []
        model.dataChanged.connect(lambda *a, **k: painted.append(1))
        scene_captures.signals.captured.emit("/elsewhere/other.hiplc")
        self.assertEqual([], painted,
                         "a capture elsewhere repainted this model")

    def test_the_model_drops_its_cached_image_and_repaints(self):
        """The two halves that make a tile actually change: dropping without repainting shows the old picture until something else invalidates the view; repainting without dropping re-serves the same decoded copy."""
        model = file_library.FileFiles(_Prefs())
        dropped, painted = [], []
        model._full_path = lambda row: "/scenes/x.hip"
        model._files = [("/scenes", "x.hip")]
        model._kinds = ["hip"]
        model._row_specs = [("KEY:/scenes/x.hip", "capture",
                             "/scenes/x.hip")]
        original = thumbnails.engine.discard
        thumbnails.engine.discard = dropped.append
        self.addCleanup(setattr, thumbnails.engine, "discard", original)
        model.dataChanged.connect(
            lambda *a, **k: painted.append(1))
        model.refresh_row(0)
        self.assertEqual(["KEY:/scenes/x.hip"], dropped,
                         "the engine's stale copy was not dropped")
        self.assertEqual(1, len(painted), "the tile was not repainted")

    def test_the_capture_path_is_wired_to_the_model(self):
        """Source-derived, because the wiring is a connect() made in a constructor a headless test cannot usefully drive: the capture must emit, and the model must listen."""
        package = os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(package, "core", "scene_captures.py"),
                  encoding="utf-8") as handle:
            code = handle.read()
        self.assertIn("signals.captured.emit(", code,
                      "a capture no longer announces itself")
        with open(os.path.join(package, "core", "file_library.py"),
                  encoding="utf-8") as handle:
            listener = handle.read()
        self.assertIn("signals.captured.connect(", listener,
                      "no model listens for a capture")
        emit_at = code.find("signals.captured.emit(")
        recorded = code.find('"thumbnail captured"')
        self.assertGreater(
            emit_at, recorded,
            "the capture is announced BEFORE it is recorded as done")


class ReviewFixesTest(unittest.TestCase):
    """Regressions for the defects a five-lens review found, each of which shipped and none of which any existing test caught."""

    def _patch(self, name, value):
        original = getattr(scene_captures, name)
        setattr(scene_captures, name, value)
        self.addCleanup(setattr, scene_captures, name, original)

    def _png(self, colours):
        from PySide6 import QtGui
        img = QtGui.QImage(64, 64, QtGui.QImage.Format.Format_ARGB32)
        img.fill(QtGui.QColor(colours[0]))
        for i, colour in enumerate(colours[1:], 1):
            for x in range(i * 8, i * 8 + 8):
                for y in range(64):
                    img.setPixelColor(x, y, QtGui.QColor(colour))
        path = os.path.join(tempfile.mkdtemp(prefix="amaze_blank_"), "t.png")
        img.save(path)
        return path

    def test_one_flat_colour_is_blank_and_two_colours_a_real_frame(self):
        """A wireframe on Houdini's flat black default samples exactly two colours: a real frame."""
        self.assertTrue(scene_captures._looks_blank(self._png(["#000000"])))
        self.assertFalse(
            scene_captures._looks_blank(self._png(["#000000", "#c8c8c8"])),
            "a two-tone frame is still reported blank")

    def test_an_empty_path_stays_empty(self):
        self.assertEqual("", scene_captures._key(""))

    def test_an_unsaved_scene_is_refused(self):
        self._patch("current_scene_path", lambda: "/nope/untitled.hip")
        self._patch("capture_thumbnail", lambda p, v=None: self.fail(
            "captured a scene that is not on disk"))
        with self.assertRaises(scene_captures.CaptureRefused) as caught:
            scene_captures.capture_open_scene()
        self.assertIn("not been saved", str(caught.exception))

    def test_the_refusal_does_not_claim_a_different_scene_wrongly(self):
        """The old wording said the viewport showed a different scene even when it showed exactly this one and Amaze merely had not opened it."""
        tmp = _Tmp(self)
        scene = tmp.touch("open.hiplc")
        self._patch("current_scene_path", lambda: scene)
        self._patch("viewport_state", lambda *a: {"blocking": False})
        self._patch("scene_viewer", lambda: "V")
        self._patch("capture_thumbnail", lambda p, v=None: "/tmp/s.png")
        scene_captures.capture_open_scene(scene)      # must NOT raise


class AnyViewerContextCanBeCapturedTest(unittest.TestCase):
    """Regression for a WRONG fix, shipped and reverted the same hour: a capture failed while the Scene View was browsing a COP network, so that context was made to REFUSE on the reasoning that a COP has nothing to photograph. False - browsing a copnet the Scene View is still a real 3D perspective viewport (grid, axis gizmo, camera, the COP output on a card in space) and it captures fine; the refusal blocked legitimate work and was inferred from one log line and a screenshot instead of tested. The network being browsed does not determine whether the viewport can be photographed - nothing here may refuse on it."""

    class _Viewer:
        def __init__(self, category):
            self._category = category

        def pwd(self):
            outer = self

            class _Node:
                def childTypeCategory(self):
                    if outer._category is None:
                        raise RuntimeError("no category here")

                    class _Cat:
                        def name(self_inner):
                            return outer._category
                    return _Cat()
            return _Node()

    def _patch(self, name, value):
        original = getattr(scene_captures, name)
        setattr(scene_captures, name, value)
        self.addCleanup(setattr, scene_captures, name, original)

    def _capture_from(self, category):
        scene = _real_scene(self)
        self._patch("current_scene_path", lambda: scene)
        self._patch("scene_viewer", lambda: self._Viewer(category))
        self._patch("viewport_state", lambda *a: {"blocking": False})
        self._patch("capture_thumbnail", lambda p, v=None: "/tmp/shot.png")
        return scene_captures.capture_open_scene(scene)

    def test_every_context_including_COP_and_an_unreadable_one_is_captured(self):
        for category in ("Object", "Lop", "Sop", "Dop", "Cop", "Chop", "Vop", None):
            with self.subTest(category=category):
                self.assertEqual(
                    "/tmp/shot.png", self._capture_from(category),
                    "a %s viewport was refused - the network being "
                    "browsed does not decide whether the viewport can "
                    "be photographed" % category)


class ShelfTest(unittest.TestCase):
    """The shelf ships with the package and is how a hotkey reaches Amaze at all: Houdini cannot bind a key to a Python Panel action."""

    def _shelf_path(self):
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))),
            "toolbar", "Amaze.shelf")

    def _shelf(self):
        import xml.etree.ElementTree as ET
        path = self._shelf_path()
        if not os.path.exists(path):
            self.fail("toolbar/Amaze.shelf is missing: %s" % path)
        return ET.parse(path).getroot()

    def test_the_shelf_is_well_formed_and_has_every_tool(self):
        root = self._shelf()
        names = sorted(t.get("name") for t in root.findall("tool"))
        self.assertEqual(["amaze_capture_hip", "amaze_check_updates",  # THE WHOLE SET, listed: a count would pass a rename and an accidental duplicate, and the names are what the refusals quote at the user
                          "amaze_open_panel", "amaze_reload", "amaze_repair_library"], names)

    def test_every_tool_is_on_the_shelf_tab(self):
        """A toolshelf is NECESSARY but not SUFFICIENT for the tab to appear - the dock is populated from shelf SETS, and a loose toolshelf belongs to none; this asserts only the part the repo controls, and the per-machine step is the manual's job. The first version stated a guarantee the package does not provide."""
        root = self._shelf()
        tools = {t.get("name") for t in root.findall("tool")}
        shelf = root.find("toolshelf")
        self.assertIsNotNone(
            shelf, "no toolshelf - the tools could not be added to a set")
        members = {m.get("name") for m in shelf.findall("memberTool")}
        self.assertEqual(
            tools, members,
            "a tool exists but is not on the tab, so nothing shows it")

    def test_every_icon_resolves_to_a_file_that_exists(self):
        root = self._shelf()
        package = os.path.dirname(self._shelf_path())  # $AMAZE is the repo/install ROOT, so the icon path resolves from there - getting this wrong failed the first version against a file that was present all along
        package = os.path.dirname(package)
        for tool in root.findall("tool"):
            icon = tool.get("icon") or ""
            self.assertTrue(icon, "%s has no icon" % tool.get("name"))
            self.assertTrue(
                icon.startswith("$AMAZE/"),
                "%s uses %r - an absolute path will not resolve on the "
                "other machine" % (tool.get("name"), icon))
            relative = icon[len("$AMAZE/"):]
            self.assertTrue(
                os.path.exists(os.path.join(package, relative)),
                "%s points at %s, which does not exist"
                % (tool.get("name"), icon))

    def test_the_capture_tool_uses_the_shared_decision_path(self):
        root = self._shelf()
        tool = [t for t in root.findall("tool")
                if t.get("name") == "amaze_capture_hip"][0]
        script = tool.find("script").text or ""
        self.assertIn("capture_open_scene", script)
        self.assertIn("CaptureRefused", script,
                      "the tool would fail silently on a refusal")

    def test_the_panel_tool_names_the_real_interface(self):
        root = self._shelf()
        tool = [t for t in root.findall("tool")
                if t.get("name") == "amaze_open_panel"][0]
        script = tool.find("script").text or ""
        self.assertIn("interfaceByName", script)
        import re as _re
        asked = _re.search(r'^INTERFACE\s*=\s*[\'"]([^\'"]+)', script, _re.M)  # CROSS-REFERENCE the two files: independent literal checks are not a comparison - renaming INTERFACE in the shelf left this green while the tool failed on every click
        self.assertIsNotNone(asked, "the tool names no interface")
        wanted = asked.group(1)
        pypanel = os.path.join(
            os.path.dirname(self._shelf_path()), "..",
            "python_panels", "Amaze.pypanel")
        with open(pypanel, encoding="utf-8") as handle:
            body = handle.read()
        self.assertIn(
            'name="%s"' % wanted, body,
            "the shelf tool asks for the %r interface but the pypanel "
            "does not declare that name" % wanted)

    def test_the_panel_tool_passes_the_interface_NAME_not_the_object(self):
        """createFloatingPaneTab's python_panel_interface is documented as the NAME of the Python Panel interface - a char const * - so passing the hou.PythonPanelInterface object returned by interfaceByName raises a TypeError the moment the tool is clicked; the API surface was probed with dir() and the docstring read as far as the signature, which is where the type is NOT stated."""
        root = self._shelf()
        tool = [t for t in root.findall("tool")
                if t.get("name") == "amaze_open_panel"][0]
        script = tool.find("script").text or ""
        start = script.find("desktop.createFloatingPaneTab")  # the CALL, not the word - it also appears in a comment above, and matching that captured the comment instead of the call
        self.assertGreater(start, -1, "the tool no longer opens a panel")
        depth = 0  # balance the parentheses: stopping at the first close cut the argument being asserted on, and the test failed against correct code
        end = start
        for i in range(script.find("(", start), len(script)):
            if script[i] == "(":
                depth += 1
            elif script[i] == ")":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        call = script[start:end]
        self.assertIn("size=", call,
                      "the call was not captured whole - this test "
                      "cannot check what it claims to")
        self.assertIn(
            "python_panel_interface=INTERFACE", call,
            "the interface is not passed by name - a call that passes "
            "the interface OBJECT raises TypeError on click")
        self.assertNotIn(
            "python_panel_interface=interface", call,
            "the interface OBJECT is being passed again")
        import re as _re
        assigned = _re.search(r'^INTERFACE\s*=\s*(.+)$', script, _re.M)  # INTERFACE must BE a name: the identifier alone is defeated by assigning interfaceByName's object to it, which re-introduces the exact TypeError while this stays green
        self.assertIsNotNone(assigned, "INTERFACE is never assigned")
        self.assertRegex(
            assigned.group(1).strip(), r'^[\'"][^\'"]+[\'"]$',
            "INTERFACE is not a string literal, so the API is handed "
            "an object again")

    def test_the_panel_tool_always_opens_a_new_window(self):
        """EVERY activation opens a fresh floating panel - there is no find-the-open-one branch, so a click can never front a window instead of giving the one that was asked for. The branch it replaces guarded against two panels sharing one index, which two pane tabs already are: a supported layout (test_thumbnail_shutdown)."""
        root = self._shelf()
        tool = [t for t in root.findall("tool")
                if t.get("name") == "amaze_open_panel"][0]
        script = re.sub(r"#.*", "", tool.find("script").text or "")  # CODE only: a comment explaining why there is no such branch must not itself read as the branch
        for spelling in ("paneTabs", "activeInterface", "setIsCurrentTab",
                         "floatingPanel", "raise_", "activateWindow"):
            self.assertNotIn(
                spelling, script,
                "the tool hunts for an open Amaze again (%s) - an "
                "activation that fronts a window opened none" % spelling)
        help_text = tool.find("helpText").text or ""
        for promise in ("raises", "already open"):
            self.assertNotIn(
                promise, help_text,
                "the help still promises to raise an open Amaze (%r), "
                "which the tool no longer does" % promise)

    def test_no_default_hotkey_is_shipped(self):
        """Choosing a key for the user silently takes one that already means something - the Hotkey Editor is where it gets assigned."""
        with open(self._shelf_path(), encoding="utf-8") as handle:
            body = handle.read()
        self.assertNotIn("<hotkey", body.lower())

    def _run_reload(self, houdini_spelling):
        """Run the Reload tool against one package holding one asset; answers it and the calls made."""
        import types
        from unittest import mock

        root = tempfile.mkdtemp(prefix="amaze_reload_")
        self.addCleanup(shutil.rmtree, root, True)
        os.makedirs(os.path.join(root, "otls"))
        asset = os.path.join(root, "otls", "probe.hda")
        with open(asset, "wb"):
            pass
        calls = []
        fake = types.ModuleType("hou")    # a module, not a namespace: H21 reads its `__name__` ▸r/module-fakes-need-a-name
        fake.getenv = lambda name: os.path.join(root, "no-such-hfs")
        fake.houdiniPath = lambda: [root]
        fake.hda = types.SimpleNamespace(
            loadedFiles=lambda: [houdini_spelling(asset)],
            reloadFile=lambda path: calls.append(("reload", path)),
            installFile=lambda path: calls.append(("install", path)))
        fake.ui = types.SimpleNamespace(setStatusMessage=lambda text: None,
                                        displayMessage=lambda *a, **k: 0)
        tool = [t for t in self._shelf().findall("tool")
                if t.get("name") == "amaze_reload"][0]
        with mock.patch.dict(sys.modules, {"hou": fake}):
            exec(compile(tool.find("script").text, "amaze_reload", "exec"),
                 {"__name__": "amaze_reload"})
        return asset, calls

    def test_reload_re_reads_a_loaded_file_houdini_spells_its_own_way(self):
        """Houdini's list and the folder scan can spell one file two ways, as Windows separators do."""
        def spelled(path):
            folder, name = os.path.split(path)
            return os.path.join(os.path.dirname(folder), ".", "otls",
                                name).replace(os.sep, "/")

        asset, calls = self._run_reload(spelled)
        self.assertEqual(
            [("reload", spelled(asset))], calls,
            "a loaded asset file was installed again as new, because "
            "the two spellings of its path were compared as text")

    def test_reload_installs_a_file_houdini_has_not_loaded(self):
        asset, calls = self._run_reload(
            lambda path: os.path.join(os.path.dirname(path), "other.hda"))
        self.assertEqual([("install", asset)], calls)

    def test_sync_install_carries_the_toolbar(self):
        """A shipped file the sync does not carry is a file that only ever exists in the repo - the documented under-sync trap."""
        tools = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))),
            "tools", "sync-install.sh")
        with open(tools, encoding="utf-8") as handle:
            body = handle.read()
        self.assertIn('amaze_mirror "$repo/toolbar"', body,  # an amaze_mirror call since the shared resolver replaced the four rsync spellings - the old assertion looked for the rsync form and read the refactor as a dropped copy
                      "sync-install.sh does not copy the toolbar")
        self.assertIn('diff -rq "$repo/toolbar"', body,
                      "the sync does not VERIFY the toolbar landed")


class CapturesLiveOutsideTheCacheTest(unittest.TestCase):
    """A hand-framed capture cannot be regenerated - rebuilding it means reconstructing the scene - and it lived under cache_root, the one directory the OS, a cache-clear preference and Delete Local Cache are all entitled to purge."""

    def setUp(self):
        self.cache = tempfile.mkdtemp(prefix="amaze_hipcap_cache_")
        self.addCleanup(shutil.rmtree, self.cache, True)
        self.config = tempfile.mkdtemp(prefix="amaze_hipcap_cfg_")
        self.addCleanup(shutil.rmtree, self.config, True)
        for name, fake in (("cache_root", self.cache),
                           ("config_root", self.config)):
            real = getattr(hostos, name)
            setattr(hostos, name, (lambda p: lambda: p)(fake))
            self.addCleanup(setattr, hostos, name, real)

    def test_the_directory_is_under_config_root(self):
        home = scene_captures.thumb_dir()
        self.assertTrue(home.startswith(self.config),
                        "captures still live in the disposable cache: %s"
                        % home)

    def test_old_captures_migrate_in(self):
        legacy = os.path.join(self.cache, "hip_thumbnails")
        os.makedirs(legacy)
        with open(os.path.join(legacy, "scene.png"), "wb") as fh:
            fh.write(b"png-bytes")
        home = scene_captures.thumb_dir()
        self.assertTrue(
            os.path.exists(os.path.join(home, "scene.png")),
            "a capture in the old cache location did not migrate - it "
            "stays where a cache clear deletes it")
        self.assertFalse(os.path.isdir(legacy),
                         "the migration left the old folder behind")

    def test_a_second_call_is_stable(self):
        first = scene_captures.thumb_dir()
        with open(os.path.join(first, "kept.png"), "wb") as fh:
            fh.write(b"x")
        second = scene_captures.thumb_dir()
        self.assertEqual(first, second)
        self.assertTrue(os.path.exists(os.path.join(second, "kept.png")))

    def test_a_newer_capture_in_the_new_home_wins_a_collision(self):
        home_dir = os.path.join(self.config, "hip_thumbnails")
        os.makedirs(home_dir)
        with open(os.path.join(home_dir, "scene.png"), "wb") as fh:
            fh.write(b"newer")
        legacy = os.path.join(self.cache, "hip_thumbnails")
        os.makedirs(legacy)
        with open(os.path.join(legacy, "scene.png"), "wb") as fh:
            fh.write(b"older")
        scene_captures.thumb_dir()
        with open(os.path.join(home_dir, "scene.png"), "rb") as fh:
            self.assertEqual(b"newer", fh.read(),
                             "an interrupted migration overwrote a newer "
                             "capture with an older one")


class SectionListIsSingleSourcedTest(unittest.TestCase):
    """Every list of sections must come from ONE place: three copies existed - the tab strip and two inside the Preferences dialog - and the two in Preferences never learned the new key, so toggling ANY section rebuilt enabled_sections from a six-entry list and dropped the tab: vanished, persisted, no switch to turn it back on, and a migration flag that would not re-add it."""

    def test_every_registered_section_is_offered(self):
        listed = [k for k, _lbl in sections.all_sections()]
        registered = [c.key for c in sections.SECTION_CLASSES]
        self.assertEqual(registered, listed)
        self.assertIn("file", listed)

    def test_every_section_has_a_label(self):
        for key, label in sections.all_sections():
            self.assertTrue(label, "section %r has no label" % key)

    def test_no_hardcoded_section_list_is_INCOMPLETE(self):
        """Source-derived, aimed at the actual defect: a literal list is not itself the bug (`_default_sections` needs one as its fallback) - the bug is a list that OMITS a registered section, and two of those lived in the Preferences dialog. Any section list in the tree must name every section."""
        import re
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        keys = {c.key for c in sections.SECTION_CLASSES}
        offenders = []
        for folder, _dirs, names in os.walk(root):
            if "__pycache__" in folder or folder.endswith("tests"):
                continue
            for name in names:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8", errors="replace") as fh:
                    body = fh.read()
                for match in re.finditer(
                        r'\[[^\[\]]*"material"[^\[\]]*\]'
                        r'|\([^()]*"material"[^()]*\)', body, re.S):
                    listed = set(re.findall(r'"([a-z]+)"', match.group()))
                    if "gradient" not in listed and "file" not in listed:
                        continue            # not a section list - the is-it-one probe keys on a CURRENT non-material key, since the old texture probe went vacuous the day that key retired
                    if "deliberately partial" in \
                            body[max(0, match.start() - 400):match.start()]:
                        continue            # a list allowed to be incomplete says so where it is declared - the exemption travels with the code it excuses
                    missing = keys - listed
                    if missing:
                        offenders.append(
                            "%s: missing %s"
                            % (os.path.relpath(path, root), sorted(missing)))
        self.assertEqual(
            [], offenders,
            "a section list omits a registered section - that is how "
            "the HIP tab was deleted: %s" % offenders)


class CleanupConfirmsBeforeDeletingTest(unittest.TestCase):
    """Source-derived: Clean Library needs a GUI, but the ordering of its dialogs is readable in the source. The rule - dialogs CONFIRM AN ACTION BEFORE IT HAPPENS, never announce that one finished - and this method had it exactly inverted: no gate at all and two completion dialogs, on a method that unlinks files and drops folder pointers and favourites, with two one-click entry points reaching it."""

    def _body(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "panel", "panel.py")
        with open(path, encoding="utf-8") as handle:
            code = handle.read()
        start = code.find("    def cleanup_db(self)")
        self.assertGreater(start, -1, "cleanup_db is gone")
        end = code.find("\n    def ", start + 10)
        return code[start:end if end > 0 else len(code)]

    def test_it_confirms_before_doing_any_work(self):
        body = self._body()
        gate = body.find("buttons=")    # not `buttons=(` - the labels are a named constant now, not a tuple literal ▸p/messages-need-one-home
        work = body.find("cleanup_db(show_dialog=False)")
        self.assertGreater(gate, -1, "there is no confirm dialog")
        self.assertGreater(work, -1)
        self.assertLess(gate, work,
                        "the confirmation comes AFTER the deleting")

    def test_the_gate_can_be_cancelled(self):
        body = self._body()
        gate = body.find("buttons=")    # not `buttons=(` - the labels are a named constant now, not a tuple literal ▸p/messages-need-one-home
        work = body.find("cleanup_db(show_dialog=False)")
        self.assertIn("return", body[gate:work],
                      "the confirm dialog cannot actually stop it")

    def test_cancel_is_the_default_and_the_close_action(self):
        """A destructive gate must not delete on Return or on Esc."""
        body = self._body()
        self.assertIn("default_choice=1", body)
        self.assertIn("close_choice=1", body)

    def test_it_does_not_announce_a_finish_with_nothing_to_say(self):
        body = self._body()
        self.assertNotIn(
            "nothing to clean.\"", body,
            "an empty result still pops a dialog - the grid already "
            "shows that nothing changed")


if __name__ == "__main__":
    unittest.main()
