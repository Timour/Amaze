"""The HIP section: scene files, and captured thumbnails. Two rules every other section follows are broken here, both pinned because both are easy to fix back into being wrong. Thumbnails are CAPTURED, never rendered: a scene cannot regenerate its thumbnail - re-rendering means reconstructing the whole scene, and the first real scene tried could not be cooked at all - so a row without a capture simply has no thumbnail and opening a folder must never start a render pass. And the store is NOT mtime-invalidated: a captured view is a hand-framed artifact, not a derived cache, and re-saving the scene must not erase it."""

import json
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
from amaze.core import captures, file_library, scene_captures, thumbnails  # noqa: E402
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


def _write_png(path, body=b"\x89PNG\r\n\x1a\n"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(body)


def _library_prefs(testcase, folders=()):
    """A _Prefs whose library folder is removed after the test."""
    preferences = _Prefs(folders)
    testcase.addCleanup(shutil.rmtree, preferences.dir, True)
    return preferences


def _settled_decoration(model, row, seconds=5.0, key=None):
    """A row's tile picture once the engine answers, repainting as a view does on `ready`."""
    import time
    from PySide6 import QtCore as _QtCore
    role = _QtCore.Qt.ItemDataRole.DecorationRole
    key = key or ("capture", model.capture_path(row))    # a File row's; an asset row passes its own
    deadline = time.time() + seconds
    shown = model.data(model.index(row, 0), role)
    while shown is None and time.time() < deadline:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.005)
        if not thumbnails.engine.is_pending(key):    # answered, or forgotten to be asked again
            shown = model.data(model.index(row, 0), role)
    return shown


class CaptureStoreTest(unittest.TestCase):
    """Captures are kept in the library, so every computer using it shows them. ▸r/tile-captures"""

    def setUp(self):
        self.tmp = _Tmp(self)
        self.scene = self.tmp.touch("scene.hiplc")
        self.prefs = _library_prefs(self, [self.tmp.dir])

    def _scene_row(self):
        model = file_library.FileFiles(self.prefs)
        model.set_folder(self.tmp.dir)
        row = model.row_for_path(self.scene)
        self.assertGreaterEqual(row, 0, "the scene is not listed")
        return model, row

    def test_a_file_capture_is_named_by_a_hash_of_its_key(self):
        """A File row has no asset id: the key its icon is kept under is hashed into the name."""
        import hashlib
        key = captures.file_key(self.prefs, self.scene)
        path = captures.file_path(self.prefs, key)
        self.assertEqual("file_" + hashlib.sha1(key.encode("utf-8")).hexdigest() + ".png",
                         os.path.basename(path))
        self.assertEqual(captures.folder(self.prefs), os.path.dirname(path))
        other = self.tmp.touch("other.hiplc")
        self.assertNotEqual(path, captures.file_path(
            self.prefs, captures.file_key(self.prefs, other)))

    def test_an_asset_capture_is_named_by_its_id_inside_the_folder(self):
        self.assertEqual(os.path.join(captures.folder(self.prefs), "abc123.png"),
                         captures.asset_path(self.prefs, "abc123"))
        with self.assertRaises(hostos.PathEscape):
            captures.asset_path(self.prefs, "../../escape")

    def test_the_shelf_and_the_tile_reach_one_file(self):
        """The shelf names a scene by its path and the menu by its row: one key, or two files."""
        model, row = self._scene_row()
        self.assertEqual(model.tile_key(row), captures.file_key(self.prefs, self.scene))
        self.assertEqual(model.capture_path(row), captures.file_path(
            self.prefs, captures.file_key(self.prefs, self.scene)))

    def test_only_a_non_empty_file_counts_as_a_capture(self):
        path = captures.file_path(self.prefs, captures.file_key(self.prefs, self.scene))
        self.assertFalse(captures.exists(path))
        _write_png(path, b"")
        self.assertFalse(captures.exists(path), "a zero-byte file was reported as a capture")
        _write_png(path)
        self.assertTrue(captures.exists(path))

    def test_the_capture_survives_the_scene_being_re_saved(self):
        """A render is dropped when its file changes; a capture is framed by hand and stays."""
        model, row = self._scene_row()
        _write_png(model.capture_path(row))
        os.utime(self.scene, (1, 1))
        with open(self.scene, "a", encoding="utf-8") as fh:
            fh.write("the scene changed")
        self.assertTrue(model.has_capture(row),
                        "re-saving the scene erased a hand-framed capture")


class CaptureRefusesOutLoudTest(unittest.TestCase):
    """Headless has no viewport, so the capture cannot succeed here - which makes this the right place to pin that it FAILS LOUDLY."""

    def setUp(self):
        self.out = os.path.join(_Tmp(self).dir, "captures", "x.png")

    def test_no_path_is_refused(self):
        with self.assertRaises(scene_captures.CaptureRefused):
            scene_captures.capture_viewport("")

    def test_headless_refusal_names_the_reason(self):
        with self.assertRaises(scene_captures.CaptureRefused) as caught:
            scene_captures.capture_viewport(self.out)
        message = str(caught.exception)
        self.assertTrue(message.strip(), "refused with no reason given")
        self.assertTrue(
            any(word in message.lower()
                for word in ("viewer", "viewport", "husd")),
            "the refusal did not say what was missing: %s" % message)

    def test_a_refusal_is_never_a_quiet_return(self):
        try:
            result = scene_captures.capture_viewport(self.out)
        except scene_captures.CaptureRefused:
            return
        self.fail("capture_viewport returned %r instead of refusing"
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
        self.out = os.path.join(self.tmp.dir, "captures", "file_abc.png")

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
        scene_captures.capture_viewport(self.out, viewer=_FakeViewer())
        self.assertTrue(self.asked_for, "the flipbook was never called")
        scratch = self.asked_for[0]
        self.assertEqual(
            ".png", os.path.splitext(scratch)[1].lower(),
            "the scratch name is %r - Houdini reads that extension as "
            "the image format and will not write a PNG"
            % os.path.basename(scratch))

    def test_the_scratch_does_not_collide_with_the_real_slot(self):
        scene_captures.capture_viewport(self.out, viewer=_FakeViewer())
        self.assertNotEqual(self.out,
                            self.asked_for[0],
                            "the capture wrote straight over the live "
                            "thumbnail - the write-aside is gone")

    def test_the_capture_lands_on_the_real_slot(self):
        result = scene_captures.capture_viewport(self.out, viewer=_FakeViewer())
        self.assertEqual(self.out, result)
        self.assertTrue(os.path.isfile(result))
        self.assertFalse(os.path.isfile(self.asked_for[0]),
                         "the scratch file was left behind")


_CAPTURE_ENTRY_POINTS = (    # every name a capture runs through; a new one joins here
    "capture_from_toolbar", "capture_onto_tile", "_capture_and_report", "_run_capture",
    "capture_open_scene", "capture_tile", "capture_viewport")


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
            if any(name in row for name in _CAPTURE_ENTRY_POINTS):
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
        for verb in (name + "(" for name in _CAPTURE_ENTRY_POINTS):    # the CALLS
            self.assertNotIn(
                verb, body,
                "opening a scene calls %s; it must only open the scene"
                % verb)

    def test_the_scan_can_actually_see_the_panel(self):
        """Guards the guard: an empty read passes every assertion above - each file scan must see the function it is aimed at."""
        panel_code = self._panel_source()
        section_code = self._sections_source()
        self.assertIn("def open_hip_scene", section_code)
        self.assertIn("def capture_onto_tile", panel_code)
        self.assertIn("def capture_from_toolbar", panel_code)
        self.assertGreater(len(panel_code), 10000)
        self.assertGreater(len(section_code), 10000)


class PlaceholderTest(unittest.TestCase):
    """A scene with no capture shows a deliberate tile, not a blank: this section can never fill the gap on its own - nothing renders in the background - so the placeholder is the resting state rather than a loading state, and an empty tile would read as broken."""

    def setUp(self):
        self.tmp = _Tmp(self)
        self.scene = self.tmp.touch("uncaptured.hiplc")
        self.prefs = _library_prefs(self, [self.tmp.dir])
        ui_helpers.forget_svg_images()
        self.addCleanup(ui_helpers.forget_svg_images)

    def test_an_uncaptured_scene_gets_the_placeholder(self):
        model = file_library.FileFiles(self.prefs)
        model.set_folder(self.tmp.dir)
        shown = _settled_decoration(model, 0)
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
        model = file_library.FileFiles(self.prefs)
        model.set_folder(self.tmp.dir)

        png = model.capture_path(0)
        _write_png(png)

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
        self.assertEqual("capture", asked[0][0][0],
                         "the engine key is not namespaced to this "
                         "section, so it could collide with another")
        self.assertIs(shown, sentinel,
                      "the engine's image was not what the tile showed")


class RepaintDoesNotStatTheDiskTest(unittest.TestCase):
    """Qt paints every visible row on every scroll, and a library can sit on a sleeping volume."""

    def setUp(self):
        self.tmp = _Tmp(self)
        self.scene = self.tmp.touch("scene.hiplc")
        self.prefs = _library_prefs(self, [self.tmp.dir])
        ui_helpers.forget_svg_images()
        self.addCleanup(ui_helpers.forget_svg_images)

    def _model(self):
        model = file_library.FileFiles(self.prefs)
        model.set_folder(self.tmp.dir)
        return model

    def _stats_of(self, wanted):
        """Stats naming `wanted` alone: os.stat is process-wide, and isfile and getsize go through it."""
        calls = []
        real = os.stat

        def counted(path, *args, **kwargs):
            if path == wanted:
                calls.append(path)
            return real(path, *args, **kwargs)

        self.addCleanup(setattr, os, "stat", real)
        os.stat = counted
        return calls

    def _paint(self, model, times=5):
        from PySide6 import QtCore as _QtCore
        for _ in range(times):
            model.data(model.index(0, 0),
                       _QtCore.Qt.ItemDataRole.DecorationRole)

    def test_a_repaint_never_stats_the_capture(self):
        """The engine reads the file off the paint thread and remembers one that is missing."""
        model = self._model()
        calls = self._stats_of(model.capture_path(0))
        self._paint(model, times=5)
        _settled_decoration(model, 0)
        self._paint(model, times=5)
        self.assertEqual(
            [], calls,
            "repaints of one un-captured scene stat'd its capture %d "
            "times - a sleeping volume stalls the grid" % len(calls))

    def test_a_zero_byte_capture_is_no_capture(self):
        """An empty file in the slot: Customize greys Capture and the tile paints its face."""
        model = self._model()
        _write_png(model.capture_path(0), b"")
        self.assertFalse(model.has_capture(0))
        self.assertIsNone(model.capture_image(0))
        from amaze.core import tile_icons
        self.assertEqual(tile_icons.generic_image("icon_hip"), _settled_decoration(model, 0),
                         "a zero-byte file was handed to the tile as this scene's capture")

    def test_a_landed_capture_forgets_the_remembered_answer(self):
        """The engine remembers a missing capture; one landing must clear that, or the face stays."""
        model = self._model()
        _settled_decoration(model, 0)
        key = ("capture", model.capture_path(0))
        self.assertTrue(thumbnails.engine.is_missing(key),
                        "the setup did not leave a remembered missing capture")
        _write_png(model.capture_path(0), _two_tone_png_bytes())
        captures.announce(model.tile_key(0))
        self.assertFalse(thumbnails.engine.is_missing(key),
                         "the engine still answers missing after a capture landed")
        shown = _settled_decoration(model, 0)
        self.assertIsNotNone(shown, "the landed capture never arrived (engine: %r)"
                             % (thumbnails.engine._states.get(key),))
        self.assertEqual((4, 4), (shown.width(), shown.height()),
                         "the tile did not pick up the capture that landed")


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

    def setUp(self):
        self.prefs = _library_prefs(self)

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
        self._patch("capture_viewport", lambda out, viewer=None: self.fail(
            "captured through a rendering delegate - the refusal fell "
            "through into an unbounded stall"))
        original = scene_captures.debug.is_on
        scene_captures.debug.is_on = lambda: debug_on
        self.addCleanup(setattr, scene_captures.debug, "is_on", original)

    def test_the_message_does_not_lecture(self):
        """One line - the person reading it knows what renderer they picked, and repeating it back is noise."""
        self._blocking()
        with self.assertRaises(scene_captures.CaptureRefused) as caught:
            scene_captures.capture_open_scene(self.prefs, self.scene)
        message = str(caught.exception)
        self.assertIn("Please stop the viewport render", message)
        self.assertNotIn("The scene view is using", message)
        self.assertNotIn("Karma", message,
                         "the renderer is named back at the user")

    def test_the_renderer_name_is_debug_mode_only(self):
        self._blocking(debug_on=True)
        with self.assertRaises(scene_captures.CaptureRefused) as caught:
            scene_captures.capture_open_scene(self.prefs, self.scene)
        self.assertIn("Detected: Karma CPU", str(caught.exception),
                      "in Debug Mode the delegate is the whole point")

    def test_the_state_is_read_before_capturing(self):
        """Order, measured rather than read: the state must be consulted BEFORE the capture, or reading it cannot avoid the stall."""
        order = []
        self.scene = _real_scene(self)
        self._patch("current_scene_path", lambda: self.scene)
        self._patch("viewport_state",
                    lambda *a: order.append("state") or {"blocking": False})
        self._patch("capture_viewport",
                    lambda out, viewer=None: order.append("capture") or out)
        scene_captures.capture_open_scene(self.prefs, self.scene)
        self.assertEqual(["state", "capture"], order)

    def test_it_refuses_rather_than_offering_to_proceed(self):
        """No capture-anyway offer: the sabotaged capture_viewport fails the test if it runs."""
        self._blocking()
        with self.assertRaises(scene_captures.CaptureRefused) as caught:
            scene_captures.capture_open_scene(self.prefs, self.scene)
        self.assertNotIn("anyway", str(caught.exception).lower())

    def test_a_tile_capture_is_refused_the_same_way(self):
        """Every tile's capture photographs the Scene View, so every one reads it first."""
        self._blocking()
        landed = []

        def heard(key):
            landed.append(key)

        captures.signals.landed.connect(heard)
        self.addCleanup(captures.signals.landed.disconnect, heard)
        with self.assertRaises(scene_captures.CaptureRefused):
            scene_captures.capture_tile(captures.asset_path(self.prefs, "abc"), "abc")
        self.assertEqual([], landed, "a refused capture was announced as landed")


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

    def test_a_row_crops_exactly_when_it_shows_a_capture(self):
        """A capture is viewport-shaped and fills its tile; every other face renders square."""
        model = file_library.FileFiles(_library_prefs(self))
        model._files = [("/tmp", "a.hip"), ("/tmp", "b.png"),
                        ("/tmp", "c.obj"), ("/tmp", "d.txt")]
        model._kinds = [file_library.kind_for(n)
                        for _f, n in model._files]

        def crops():
            return [bool(model.data(model.index(i, 0), model.CropRole)) for i in range(4)]

        self.assertEqual([True, False, False, False], crops(),
                         "only a scene shows its capture until another tile is given one")
        model.tile_icon = lambda row: {"face": "capture"} if row == 1 else {}
        self.assertEqual([True, True, False, False], crops(),
                         "an image showing its capture does not fill the tile")
        model.tile_icon = lambda row: {"face": "generic"} if row == 0 else {}
        self.assertEqual([False, False, False, False], crops(),
                         "a scene showing its generic face still crops")


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
        cls.hidden_at_construction = cls.panel.btn_hip_capture.isHidden()    # before any tab switch

    def _row(self):
        return test_support.toolbar_row(self.panel)

    def test_it_is_on_the_toolbar_from_the_start(self):
        """Every library tile takes a capture, so no section hides the button."""
        self.assertFalse(self.hidden_at_construction,
                         "the capture button is hidden on a freshly built panel")

    def test_the_button_is_live_in_every_section(self):
        """Driven through the real tab switch, not read off a visibility line in panel.py."""
        for key in [cls.key for cls in sections.SECTION_CLASSES]:
            with self.subTest(section=key):
                self.panel._on_tab_toggled(key, True)
                self.assertFalse(self.panel.btn_hip_capture.isHidden(),
                                 "the capture button is hidden in %s" % key)
                self.assertTrue(self.panel.btn_hip_capture.isEnabled(),
                                "the capture button is greyed in %s" % key)

    def test_every_local_tile_delegate_can_crop_a_capture(self):
        """A capture fills its tile in every section; an online tile has none."""
        for name in ("thumb_delegate", "asset_delegate", "code_delegate",
                     "file_delegate", "gradient_delegate"):
            with self.subTest(delegate=name):
                self.assertIsNotNone(getattr(self.panel, name)._crop_role,
                                     "%s letterboxes a capture" % name)
        self.assertIsNone(self.panel.matx_delegate._crop_role)

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

    def setUp(self):
        self.prefs = _library_prefs(self)

    def _patch(self, name, value):
        original = getattr(scene_captures, name)
        setattr(scene_captures, name, value)
        self.addCleanup(setattr, scene_captures, name, original)

    def test_no_open_scene_is_refused_with_a_reason(self):
        self._patch("current_scene_path", lambda: "")
        with self.assertRaises(scene_captures.CaptureRefused) as caught:
            scene_captures.capture_open_scene(self.prefs)
        self.assertIn("nothing to capture", str(caught.exception).lower())

    def test_a_target_that_is_not_open_is_refused(self):
        self.scene = _real_scene(self)
        self._patch("current_scene_path", lambda: self.scene)
        with self.assertRaises(scene_captures.CaptureRefused) as caught:
            scene_captures.capture_open_scene(self.prefs, _real_scene(self, "other.hiplc"))
        self.assertIn("different scene", str(caught.exception))

    def test_a_rendering_viewport_is_refused(self):
        self.scene = _real_scene(self)
        self._patch("current_scene_path", lambda: self.scene)
        self._patch("viewport_state",
                    lambda *a: {"blocking": True, "renderer": "Karma CPU"})
        self._patch("capture_viewport",
                    lambda out, viewer=None: self.fail("captured through a renderer"))
        with self.assertRaises(scene_captures.CaptureRefused) as caught:
            scene_captures.capture_open_scene(self.prefs, self.scene)
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
        self._patch("capture_viewport",
                    lambda out, viewer=None: handed.append(("shot", viewer)) or out)
        scene_captures.capture_open_scene(self.prefs, self.scene)
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
        self._patch("capture_viewport",
                    lambda out, viewer=None: taken.append(out) or out)
        out = scene_captures.capture_open_scene(self.prefs)
        expected = captures.file_path(self.prefs, captures.file_key(self.prefs, self.scene))
        self.assertEqual([expected], taken, "the open scene's capture went somewhere else")
        self.assertEqual(expected, out)

    def test_no_panel_entry_point_re_decides(self):
        """Source-derived: EVERY capture entry point must delegate. The first version read only the right-click handler while the toolbar button was a separate method carrying its own copy of the policy and its own wording - the test written to prevent that drift never looked at the method that had it."""
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "panel", "panel.py")
        with open(path, encoding="utf-8") as handle:
            code = handle.read()
        for name, shared in (("capture_from_toolbar", ("capture_onto_tile(", "_capture_and_report(")),
                             ("capture_onto_tile", ("capture_tile(", "_capture_and_report(")),
                             ("_capture_and_report", ("capture_open_scene(",))):
            start = code.find("def %s" % name)
            self.assertGreater(start, -1, "%s is gone" % name)
            end = code.find("\n    def ", start + 10)
            body = re.sub(r"#.*", "", code[start:end if end > 0 else len(code)])
            for call in shared:
                self.assertIn(call, body, "%s does not use the shared path" % name)
            for owned in ("viewport_state(", "displayMessage(", "capture_viewport("):    # unguarded
                self.assertNotIn(
                    owned, body,
                    "%s re-decides with %s - that belongs to "
                    "scene_captures, once" % (name, owned))


class CaptureRefreshesTheTileTest(unittest.TestCase):
    """Regression: the shelf tool captured correctly - the PNG replaced each time - and the tile did not change. The engine keeps a decoded copy in memory and nothing invalidated it, because the REFRESH lived in the panel button right after its own call rather than in the capture; one caller hid that, a second exposed it immediately."""

    def test_the_whole_chain_repaints_the_right_row(self):
        """END TO END: emit -> slot -> row_for_path -> refresh_row. The original three cases tested the links and never the chain, so replacing _on_capture_landed's body with a bare return left them all green - the regression this class is named for, twice shipped. The case this replaces emitted the signal itself after connecting its own listener, which tested PySide rather than Amaze."""
        tmp = _Tmp(self)
        scene = tmp.touch("one.hiplc")
        tmp.touch("two.hiplc")
        model = file_library.FileFiles(_library_prefs(self, [tmp.dir]))
        model.set_folder(tmp.dir)
        row = model.row_for_path(scene)
        dropped, painted = [], []
        original = thumbnails.engine.discard
        thumbnails.engine.discard = dropped.append
        self.addCleanup(setattr, thumbnails.engine, "discard", original)
        model.dataChanged.connect(
            lambda tl, br, roles=None: painted.append(tl.row()))

        captures.signals.landed.emit(model.tile_key(row))

        self.assertEqual(
            [row], painted,
            "the capture did not repaint the row for the captured scene")
        self.assertIn(("capture", model.capture_path(row)), dropped,    # other live panels drop theirs
                      "the engine's stale copy was not dropped")

    def test_an_unrelated_scene_does_not_repaint_anything(self):
        """The slot must find the RIGHT row, not merely any row."""
        tmp = _Tmp(self)
        tmp.touch("one.hiplc")
        model = file_library.FileFiles(_library_prefs(self, [tmp.dir]))
        model.set_folder(tmp.dir)
        painted = []
        model.dataChanged.connect(lambda *a, **k: painted.append(1))
        captures.signals.landed.emit("/elsewhere/other.hiplc")
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

    def test_the_capture_path_is_wired_to_the_models(self):
        """Source-derived: a capture is announced once it lands; both model families listen."""
        package = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        def read(name):
            with open(os.path.join(package, "core", name), encoding="utf-8") as handle:
                return handle.read()

        code = read("scene_captures.py")
        start = code.find("def capture_tile")
        self.assertGreater(start, -1, "capture_tile is gone")
        body = code[start:code.find("\ndef ", start + 10)]
        self.assertIn("captures.announce(", body, "a capture no longer announces itself")
        self.assertGreater(body.find("captures.announce("), body.find("capture_viewport("),
                           "the capture is announced BEFORE it has landed")
        for module in ("file_library.py", "library.py"):
            self.assertIn("captures.signals.landed.connect(", read(module),
                          "%s does not listen for a capture" % module)


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
        self._patch("capture_viewport", lambda out, viewer=None: self.fail(
            "captured a scene that is not on disk"))
        with self.assertRaises(scene_captures.CaptureRefused) as caught:
            scene_captures.capture_open_scene(_library_prefs(self))
        self.assertIn("not been saved", str(caught.exception))

    def test_the_refusal_does_not_claim_a_different_scene_wrongly(self):
        """The old wording said the viewport showed a different scene even when it showed exactly this one and Amaze merely had not opened it."""
        tmp = _Tmp(self)
        scene = tmp.touch("open.hiplc")
        self._patch("current_scene_path", lambda: scene)
        self._patch("viewport_state", lambda *a: {"blocking": False})
        self._patch("scene_viewer", lambda: "V")
        self._patch("capture_viewport", lambda out, viewer=None: out)
        scene_captures.capture_open_scene(_library_prefs(self), scene)      # must NOT raise


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
        self._patch("capture_viewport", lambda out, viewer=None: "/tmp/shot.png")
        return scene_captures.capture_open_scene(_library_prefs(self), scene)

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


class MachineCapturesAreAdoptedTest(unittest.TestCase):
    """Before 1.9 each computer kept its own scene captures; they move into the library."""

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
        from amaze.core import locations
        self.locations = locations
        real_ready = locations.ready
        locations.ready = lambda preferences: True    # the stub has no store to wait for
        self.addCleanup(setattr, locations, "ready", real_ready)
        self.prefs = _library_prefs(self)
        self.scene = _real_scene(self)

    def _old(self, root, scene, body=b"old-capture", name="0123abcd.png"):
        """`root`'s old capture folder holding one capture of `scene`, mapped by its manifest."""
        folder = os.path.join(root, captures.LEGACY_FOLDER)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, name), "wb") as fh:
            fh.write(body)
        manifest = os.path.join(folder, "manifest.json")
        mapped = {}
        if os.path.isfile(manifest):
            with open(manifest, encoding="utf-8") as fh:
                mapped = json.load(fh)
        mapped[hostos.canonical_path_key(scene)] = {"thumbnail": name}
        with open(manifest, "w", encoding="utf-8") as fh:
            json.dump(mapped, fh)
        return os.path.join(folder, name)

    def _target(self, scene, preferences=None):
        preferences = preferences or self.prefs
        return captures.file_path(preferences, captures.file_key(preferences, scene))

    @staticmethod
    def _read(path):
        with open(path, "rb") as fh:
            return fh.read()

    def _held(self, name):
        """Where a moved original waits in the holding folder."""
        from amaze.core import quarantine
        return os.path.join(quarantine.quarantine_folder(self.prefs.dir),
                            captures.LEGACY_FOLDER, name)

    def test_an_old_capture_moves_into_the_library(self):
        source = self._old(self.config, self.scene)
        self.assertEqual(1, captures.adopt_machine_captures(self.prefs))
        self.assertEqual(b"old-capture", self._read(self._target(self.scene)))
        self.assertFalse(os.path.exists(source), "the original was left behind")
        self.assertEqual(b"old-capture", self._read(self._held(os.path.basename(source))),
                         "the original is not in the holding folder")
        self.assertFalse(os.path.isdir(os.path.dirname(source)),
                         "the emptied old folder stayed")

    def test_both_old_folders_are_read(self):
        """The settings folder, and the cache folder an older install kept them in."""
        other = _real_scene(self, "other.hiplc")
        self._old(self.config, self.scene)
        self._old(self.cache, other, body=b"from-cache")
        self.assertEqual(2, captures.adopt_machine_captures(self.prefs))
        self.assertEqual(b"from-cache", self._read(self._target(other)))

    def test_a_second_start_finds_nothing_to_move(self):
        self._old(self.config, self.scene)
        captures.adopt_machine_captures(self.prefs)
        self.assertEqual(0, captures.adopt_machine_captures(self.prefs))
        self.assertEqual(0, captures.adopt_machine_captures(_library_prefs(self)),
                         "a capture moved into one library was offered to the next")

    def test_a_capture_already_in_the_library_wins(self):
        """Another computer may have captured the scene since: the library keeps its own."""
        source = self._old(self.config, self.scene)
        _write_png(self._target(self.scene), b"newer")
        self.assertEqual(0, captures.adopt_machine_captures(self.prefs))
        self.assertEqual(b"newer", self._read(self._target(self.scene)))
        self.assertEqual(b"old-capture", self._read(self._held(os.path.basename(source))),
                         "this computer's older capture was not kept in the holding folder")

    def test_nothing_moves_before_files_can_be_keyed(self):
        """A capture keyed by its path now would miss its row once the locations are read."""
        self.locations.ready = lambda preferences: False
        source = self._old(self.config, self.scene)
        self.assertEqual(0, captures.adopt_machine_captures(self.prefs))
        self.assertFalse(os.path.exists(self._target(self.scene)))
        self.assertTrue(os.path.isfile(source), "a capture moved before its key could be read")

    def test_a_capture_that_cannot_be_copied_waits_for_the_next_start(self):
        from unittest import mock
        source = self._old(self.config, self.scene)
        with mock.patch.object(captures.shutil, "copyfile", side_effect=OSError("disk full")):
            self.assertEqual(0, captures.adopt_machine_captures(self.prefs))
        self.assertTrue(os.path.isfile(source), "a capture that was not copied was set aside")
        manifest = os.path.join(os.path.dirname(source), captures.LEGACY_MANIFEST)
        with open(manifest, encoding="utf-8") as fh:
            self.assertIn(hostos.canonical_path_key(self.scene), json.load(fh),
                          "the next start no longer knows which scene it belongs to")
        self.assertEqual(1, captures.adopt_machine_captures(self.prefs))

    def test_an_entry_without_its_file_is_skipped(self):
        os.remove(self._old(self.config, self.scene))
        self.assertEqual(0, captures.adopt_machine_captures(self.prefs))
        self.assertFalse(os.path.exists(self._target(self.scene)))

    def test_the_count_is_what_waits_to_move(self):
        self._old(self.config, self.scene)
        self._old(self.cache, _real_scene(self, "other.hiplc"), name="9999abcd.png")
        self.assertEqual(2, captures.machine_capture_count())
        captures.adopt_machine_captures(self.prefs)
        self.assertEqual(0, captures.machine_capture_count())


class LibraryUpdateTest(unittest.TestCase):
    """Opening a library brings it to this Amaze's version; old captures move only when asked."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def setUp(self):
        from amaze.core import library_policy
        self.policy = library_policy
        self.dir = self.panel.prefs.dir
        library_policy.set_library_version(self.dir, 1)    # a library from before 1.9
        self.moved, self.asked = [], []
        self._patch(captures, "adopt_machine_captures",
                    lambda preferences: self.moved.append(preferences) or 0)

    def _patch(self, owner, name, value):
        original = getattr(owner, name)
        setattr(owner, name, value)
        self.addCleanup(setattr, owner, name, original)

    def _answer(self, choice):
        """The dialog, answered with button `choice`: 0 Update Library, 1 Later."""
        import types
        from unittest import mock

        def display(text, **kwargs):
            self.asked.append((text, kwargs))
            return choice

        patcher = mock.patch.object(hou, "ui", types.SimpleNamespace(displayMessage=display),
                                    create=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_this_computers_captures_move_when_asked(self):
        self._patch(captures, "machine_capture_count", lambda: 3)
        self._answer(0)
        self.panel._update_library()
        self.assertEqual(1, len(self.moved), "the captures were not moved")
        self.assertEqual(2, self.policy.library_version(self.dir))
        text, kwargs = self.asked[0]
        self.assertEqual("Update this library to version 2?", text)
        self.assertIn("the 3 captures on this computer", kwargs["help"])
        self.assertEqual(("Update Library", "Later"), tuple(kwargs["buttons"]))

    def test_later_moves_nothing_and_keeps_the_version(self):
        self._patch(captures, "machine_capture_count", lambda: 1)
        self._answer(1)
        self.panel._update_library()
        self.assertEqual([], self.moved, "Later moved the captures")
        self.assertEqual(1, self.policy.library_version(self.dir))
        self.assertIn("the 1 capture on this computer", self.asked[0][1]["help"])

    def test_with_nothing_to_move_it_updates_without_asking(self):
        self._patch(captures, "machine_capture_count", lambda: 0)
        self._answer(0)
        self.panel._update_library()
        self.assertEqual([], self.asked, "a dialog asked about nothing")
        self.assertEqual(2, self.policy.library_version(self.dir))

    def test_an_updated_library_asks_only_about_this_computer(self):
        from amaze import messages
        self.policy.set_library_version(self.dir, 2)
        self._patch(captures, "machine_capture_count", lambda: 2)
        self._answer(0)
        self.panel._update_library()
        self.assertEqual(messages.LIBRARY_CAPTURES_MOVE_CONFIRM, self.asked[0][0])
        self.assertEqual(1, len(self.moved))


class AssetCaptureTest(unittest.TestCase):
    """Any library tile can show a capture, kept as `captures/<id>.png`, filling the tile."""

    def setUp(self):
        from amaze.core import library
        self.prefs = test_support.fixture_prefs(self)
        self.model = library.MaterialLibrary(self.prefs)
        self.assertGreater(self.model.rowCount(), 0, "the fixture library is empty")

    def test_the_capture_is_kept_under_the_asset_id(self):
        self.assertEqual(captures.asset_path(self.prefs, self.model.tile_key(0)),
                         self.model.capture_path(0))

    def test_the_capture_face_reads_the_capture_and_fills_the_tile(self):
        rendered = self.model._thumb_key(0)
        self.assertFalse(self.model.data(self.model.index(0, 0), self.model.CropRole))
        self.assertTrue(self.model.set_tile_icon(0, {"face": "capture"}))
        self.assertEqual(self.model.capture_path(0), self.model._mat_paths[0])
        self.assertTrue(self.model.data(self.model.index(0, 0), self.model.CropRole))
        self.assertNotEqual(rendered, self.model._thumb_key(0),
                            "the capture shares the render's cached picture")

    def test_a_landed_capture_repaints_the_asset(self):
        self.model.set_tile_icon(0, {"face": "capture"})
        dropped, painted = [], []
        original = thumbnails.engine.discard
        thumbnails.engine.discard = dropped.append
        self.addCleanup(setattr, thumbnails.engine, "discard", original)
        self.model.dataChanged.connect(lambda tl, br, roles=None: painted.append(tl.row()))
        captures.signals.landed.emit(self.model.tile_key(0))
        self.assertEqual([0], painted, "the captured tile was not repainted")
        self.assertIn(self.model._thumb_key(0), dropped, "the old picture was kept")

    def test_the_capture_is_one_of_the_files_an_asset_owns(self):
        """Delete, Copy To and packages walk this list, so the capture goes with its asset."""
        self.assertEqual(captures.asset_path(self.prefs, "abc"),
                         self.model.asset_files("abc")["capture"])

    def test_capture_is_offered_once_the_tile_has_one(self):
        self.assertFalse(self.model.has_capture(0))
        self.assertIsNone(self.model.capture_image(0))
        _write_png(self.model.capture_path(0), _two_tone_png_bytes())
        self.assertTrue(self.model.has_capture(0))
        self.assertIsNotNone(self.model.capture_image(0))


class CaptureFromTheMenuTest(unittest.TestCase):
    """Capture on the right-click menu and the toolbar, driven on a real panel."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _patch(self, owner, name, value):
        original = getattr(owner, name)
        setattr(owner, name, value)
        self.addCleanup(setattr, owner, name, original)

    def _select(self, key, rows):
        """Show section `key` with `rows` selected; answers its context and the selection."""
        from PySide6 import QtCore as _QtCore
        panel = self.panel
        panel.section_tabs.setChecked(key)
        QtWidgets.QApplication.processEvents()
        proxy = panel.thumblist.model()
        selection = panel.thumblist.selectionModel()
        selection.clearSelection()
        for row in rows:
            selection.select(proxy.index(row, 0),
                             _QtCore.QItemSelectionModel.SelectionFlag.Select)
        context = panel._section()
        chosen = context.grid_selection()
        self.assertEqual(len(rows), len(chosen), "the selection is not what the test says")
        return context, chosen

    def _rows_of_kind(self, kind):
        self._select("file", [])
        proxy = self.panel.thumblist.model()
        role = self.panel.file_files_model.KindRole
        return [row for row in range(proxy.rowCount())
                if (proxy.index(row, 0).data(role) or "") == kind]

    def _refusals(self):
        said = []
        self._patch(self.panel, "_report_capture_refused", said.append)
        return said

    def test_one_tile_in_any_section_can_be_captured(self):
        for key in ("material", "code", "gradient"):
            with self.subTest(section=key):
                context, chosen = self._select(key, [0, 1])
                self.assertTrue(context.menu_capture_enabled(chosen[:1], chosen[0]))
                self.assertFalse(context.menu_capture_enabled(chosen, chosen[0]),
                                 "one capture was offered for two tiles")

    def test_a_scene_is_captured_only_while_it_is_the_open_one(self):
        rows = self._rows_of_kind(file_library.KIND_HIP)
        context, chosen = self._select("file", rows[:1])
        path = chosen[0].data(self.panel.file_files_model.PathRole)
        self._patch(scene_captures, "current_scene_path", lambda: "")
        self.assertFalse(context.menu_capture_enabled(chosen, chosen[0]),
                         "a scene that is not open was offered a capture")
        self._patch(scene_captures, "current_scene_path", lambda: path)
        self.assertTrue(context.menu_capture_enabled(chosen, chosen[0]))

    def test_any_other_file_takes_a_capture(self):
        rows = self._rows_of_kind(file_library.KIND_IMAGE)
        context, chosen = self._select("file", rows[:1])
        self.assertTrue(context.menu_capture_enabled(chosen, chosen[0]))

    def test_a_capture_lands_on_the_tile_and_the_tile_shows_it(self):
        from amaze.core import tile_icons
        context, chosen = self._select("material", [0])
        model, proxy = context.tile_models()
        row = proxy.mapToSource(chosen[0]).row()
        taken = []

        def capture(out, key):
            _write_png(out, _two_tone_png_bytes())
            taken.append((out, key))
            return out

        self._patch(scene_captures, "capture_tile", capture)
        self.addCleanup(model.set_tile_icons, [row], {})
        self.panel.capture_onto_tile(context, chosen[0])
        self.assertEqual([(model.capture_path(row), model.tile_key(row))], taken)
        self.assertEqual("capture", tile_icons.face_for(model, row),
                         "the tile went on showing its render")

    def test_every_kind_of_asset_tile_paints_its_capture(self):
        """Code and Color paint their own pictures in RAM; their Capture face reads the file."""
        for name in ("material_model", "code_model", "gradient_model"):    # the fixture has no Nodes
            with self.subTest(model=name):
                model = getattr(self.panel, name)
                self.assertGreater(model.rowCount(), 0, "the fixture has no %s rows" % name)
                _write_png(model.capture_path(0), _two_tone_png_bytes())
                self.addCleanup(model.set_tile_icons, [0], {})
                self.assertTrue(model.set_tile_icon(0, {"face": "capture"}))
                shown = _settled_decoration(model, 0, key=model._thumb_key(0))
                self.assertIsNotNone(shown, "the capture never painted")
                self.assertEqual((4, 4), (shown.width(), shown.height()),
                                 "the tile shows something other than its capture")

    def test_a_refused_capture_says_why_and_leaves_the_tile(self):
        context, chosen = self._select("material", [0])
        model, proxy = context.tile_models()
        row = proxy.mapToSource(chosen[0]).row()
        before = model.tile_icon(row)

        def refuse(out, key):
            raise scene_captures.CaptureRefused("Please stop the viewport render before capturing.")

        self._patch(scene_captures, "capture_tile", refuse)
        said = self._refusals()
        self.panel.capture_onto_tile(context, chosen[0])
        self.assertEqual(["Please stop the viewport render before capturing."], said)
        self.assertEqual(before, model.tile_icon(row), "a refused capture changed the tile")

    def test_the_toolbar_asks_for_one_tile(self):
        from amaze import messages
        self._select("material", [])
        said = self._refusals()
        self._patch(scene_captures, "capture_tile",
                    lambda out, key: self.fail("captured onto no tile"))
        self.panel.capture_from_toolbar()
        self.assertEqual([messages.CAPTURE_SELECT_ONE_TILE], said)

    def test_the_toolbar_in_File_with_nothing_selected_takes_the_open_scene(self):
        self._select("file", [])
        asked = []
        self._patch(scene_captures, "capture_open_scene",
                    lambda preferences, target="": asked.append(target) or "")
        self.panel.capture_from_toolbar()
        self.assertEqual([""], asked, "the open scene was not captured")


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
