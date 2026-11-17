"""Scene files: thumbnails are captured, never rendered, and a re-save never invalidates them."""

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
from amaze.actions import files as files_actions  # noqa: E402
from amaze.core import captures, file_library, locations, scene_captures, scene_files, section_list, thumbnails, tile_icons  # noqa: E402
from amaze.helpers import hostos, ui_helpers  # noqa: E402
from amaze.panel import sections  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401


class _Prefs:
    """Only the prefs the File model's scene rows read; hip rows are handled in FileFiles."""

    def __init__(self, folders=(), favorites=(), subfolders=False,
                 dir=""):
        self.dir = dir or tempfile.mkdtemp(prefix="amaze_hip_prefs_")  # tile_icons reads .dir to find the library's icons.json
        self.file_folders = list(folders)
        self.file_favorites = list(favorites)
        self.file_recursive_folders = list(folders) if subfolders else []  # recursion is per LOCATION: the stub's flag marks every registered folder recursive
        self.file_folder_names = {}
        self.last_file_folder = ""
        self.file_show_unknown = True    # a folder no location holds lists by this switch
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
    """A scene file that exists on disk, since capture_open_scene refuses a target that does not."""
    folder = tempfile.mkdtemp(prefix="amaze_scene_")
    testcase.addCleanup(shutil.rmtree, folder, ignore_errors=True)
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("x")
    return path


class ExtensionsAreOneTypeTest(unittest.TestCase):
    """A .hiplc beside a .hip shows both: the licence flavour is never a category."""

    def test_every_scene_extension_and_nothing_else_is_recognised(self):
        for name, scene in (("a.hip", True), ("b.hiplc", True), ("c.hipnc", True),
                            ("D.HIP", True), ("E.HipLC", True), ("a.hda", False),
                            ("b.bgeo", False), ("c.usd", False), ("d.hip.bak", False),
                            ("e.txt", False), ("notahip", False)):
            with self.subTest(name=name):
                self.assertEqual(scene, bool(scene_files.matched_extension(name)))

    def test_the_listing_shows_all_three_flavours(self):
        """All three scene extensions are one kind; the geometry decoy is a row, not a scene row."""
        tmp = _Tmp(self)
        for name in ("one.hip", "two.hiplc", "three.hipnc", "skip.bgeo"):
            tmp.touch(name)
        model = file_library.FileFiles(_Prefs([tmp.dir]))
        model.set_folder(tmp.dir)
        self.assertEqual(4, model.rowCount(),
                         "the File section no longer lists every file")
        kinds = [model.data(model.index(i, 0), model.KindRole)
                 for i in range(model.rowCount())]
        self.assertEqual(3, kinds.count(locations.KIND_HIP),
                         "the section did not treat all three scene "
                         "extensions as one type")


class FormatLabelTest(unittest.TestCase):

    def test_the_format_column_is_title_case(self):
        """Hiplc, not HIPLC: a scene extension reads as a word, unlike the .OBJ/.EXR acronyms."""
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
    """A row's tile image once `thumbnails.engine` has it, re-reading as a view does on `ready`."""
    import time
    from PySide6 import QtCore as _QtCore
    role = _QtCore.Qt.ItemDataRole.DecorationRole
    key = key or ("capture", model.capture_path(row))    # a File row's; an asset row passes its own
    deadline = time.time() + seconds
    shown = model.data(model.index(row, 0), role)
    while (shown is None or thumbnails.engine.is_pending(key)) and time.time() < deadline:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.005)
        if not thumbnails.engine.is_pending(key):    # loaded, or dropped so the next read requests it again
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
        self.assertEqual(hashlib.sha1(key.encode("utf-8")).hexdigest() + ".png",
                         os.path.basename(path))
        self.assertEqual(captures.folder(self.prefs), os.path.dirname(path))
        other = self.tmp.touch("other.hiplc")
        self.assertNotEqual(path, captures.file_path(
            self.prefs, captures.file_key(self.prefs, other)))

    def test_an_asset_capture_is_named_by_its_id_inside_its_section_folder(self):
        """An asset's capture is its one picture, `<section folder>/<id>.png`."""
        for section, folder in (("materials.json", "materials"), ("nodes.json", "nodes"),
                                ("code.json", "code"), ("colors.json", "colors")):
            with self.subTest(section=section):
                self.assertEqual(os.path.join(str(self.prefs.dir), folder, "abc123.png"),
                                 tile_icons.thumbnail_path(self.prefs, "abc123", section))
                with self.assertRaises(hostos.PathEscape):
                    tile_icons.thumbnail_path(self.prefs, "../../escape", section)

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
    """Headless has no viewport, so the capture fails here and must raise, not return quietly."""

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
            "the error message does not name what was missing: %s" % message)

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
    """The scratch file keeps the real extension: Houdini picks the image format from it."""

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
            self.asked_for.append(output)  # writes whatever the name, so the assertion is about the name
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
                            "thumbnail - the scratch-file write is gone")

    def test_the_capture_lands_on_the_real_slot(self):
        result = scene_captures.capture_viewport(self.out, viewer=_FakeViewer())
        self.assertEqual(self.out, result)
        self.assertTrue(os.path.isfile(result))
        self.assertFalse(os.path.isfile(self.asked_for[0]),
                         "the scratch file was left behind")


_CAPTURE_ENTRY_POINTS = (    # every function a capture runs through; add new ones here
    "from_toolbar", "onto_tile", "capture_and_report", "tile_capture.run", "self.run(",
    "capture_open_scene", "capture_tile", "capture_viewport")


class NoAutomaticCaptureTest(unittest.TestCase):
    """No automatic capture: a capture runs a flipbook, which cooks the scene, unbounded work."""

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
            line = ""  # a space between two word-ish tokens, or a def and its name fuse
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
        """open_hip_scene is a FileSection method, so the scans for it read sections.py."""
        return self._stripped_source("sections.py")

    def test_nothing_schedules_a_capture(self):
        """Comments and docstrings are stripped first; the panel, sections and helper sources are read."""
        code = (self._panel_source() + "\n" + self._sections_source() + "\n"
                + self._stripped_source("online_import.py") + "\n"
                + self._stripped_source("package_import.py") + "\n"
                + self._stripped_source("drop_placement.py") + "\n"
                + self._stripped_source("tile_capture.py"))
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
        """Checks the scan itself: each file scan must find the function it looks for."""
        panel_code = self._panel_source()
        section_code = self._sections_source()
        capture_code = self._stripped_source("tile_capture.py")
        self.assertIn("def open_hip_scene", section_code)
        self.assertIn("def onto_tile", capture_code)
        self.assertIn("def from_toolbar", capture_code)
        self.assertGreater(len(panel_code), 10000)
        self.assertGreater(len(section_code), 10000)


class PlaceholderTest(unittest.TestCase):
    """A scene with no capture shows the placeholder tile image, never a blank."""

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
        """A capture loads through thumbnails.engine, never decoded in data(); the wiring is asserted."""
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
    """Qt paints every visible row on every scroll, and a library can be on a sleeping volume."""

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
        """`thumbnails.engine` reads the file off the paint thread and caches a missing one."""
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
        """An empty capture file: Customize disables Capture; the tile paints its default face."""
        model = self._model()
        _write_png(model.capture_path(0), b"")
        self.assertFalse(model.has_capture(0))
        self.assertIsNone(model.capture_image(0))
        from amaze.core import tile_icons
        self.assertEqual(tile_icons.generic_image("icon_hip"), _settled_decoration(model, 0),
                         "a zero-byte file was handed to the tile as this scene's capture")

    def test_a_landed_capture_forgets_the_remembered_answer(self):
        """The engine caches a missing capture; a new capture must clear that, or the face stays."""
        model = self._model()
        _settled_decoration(model, 0)
        key = ("capture", model.capture_path(0))
        self.assertTrue(thumbnails.engine.is_missing(key),
                        "the setup did not leave a remembered missing capture")
        _write_png(model.capture_path(0), _two_tone_png_bytes())
        captures.announce(model.tile_key(0))
        self.assertFalse(thumbnails.engine.is_missing(key),
                         "the engine still reports missing after a capture was written")
        shown = _settled_decoration(model, 0)
        self.assertIsNotNone(shown, "the written capture was never shown (engine: %r)"
                             % (thumbnails.engine._states.get(key),))
        self.assertEqual((4, 4), (shown.width(), shown.height()),
                         "the tile did not show the new capture")


class ViewportStateTest(unittest.TestCase):
    """Read the viewport first: every capture route renders, so a pathtracer makes it unbounded."""

    def test_only_the_houdini_delegates_are_fast(self):
        for name, fast in (("Houdini VK", True), ("Houdini GL", True), ("houdini vk", True),
                           ("  Houdini VK  ", True), ("Karma CPU", False),
                           ("Karma XPU", False), ("Redshift", False), ("Arnold", False)):
            with self.subTest(name=name):
                self.assertEqual(fast, scene_captures.delegate_is_fast(name))

    def test_an_obj_viewport_is_not_blocked(self):
        """An OBJ viewport is not Hydra-based, so currentHydraRenderer() raises; it must not block."""
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
        """Only a delegate positively recognised as a renderer blocks; everything else proceeds."""
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


def _patch(testcase, owner, name, value):
    """`owner.name` is `value` for this test, put back when it ends."""
    from unittest import mock
    patcher = mock.patch.object(owner, name, value)
    patcher.start()
    testcase.addCleanup(patcher.stop)


class SlowCapturePromptTest(unittest.TestCase):
    """The refusal's message and behaviour when the viewport renders, through capture_open_scene."""

    def setUp(self):
        self.prefs = _library_prefs(self)

    def _blocking(self, debug_on=False):
        """Karma renders the viewport; capture_viewport is replaced to fail the test if called."""
        self.scene = _real_scene(self)
        _patch(self, scene_captures, "current_scene_path", lambda: self.scene)
        _patch(self, scene_captures, "viewport_state",
               lambda *a: {"blocking": True, "renderer": "Karma CPU"})
        _patch(self, scene_captures, "capture_viewport", lambda out, viewer=None: self.fail(
            "captured through a rendering delegate - the refusal did "
            "not stop it, so the capture could stall without limit"))
        original = scene_captures.debug.is_on
        scene_captures.debug.is_on = lambda: debug_on
        self.addCleanup(setattr, scene_captures.debug, "is_on", original)

    def test_the_message_does_not_lecture(self):
        """One line: whoever reads it knows the renderer they picked."""
        self._blocking()
        with self.assertRaises(scene_captures.CaptureRefused) as caught:
            scene_captures.capture_open_scene(self.prefs, self.scene)
        message = str(caught.exception)
        self.assertIn("Please stop the viewport render", message)
        self.assertNotIn("The scene view is using", message)
        self.assertNotIn("Karma", message,
                         "the message names the renderer to the user")

    def test_the_renderer_name_is_debug_mode_only(self):
        self._blocking(debug_on=True)
        with self.assertRaises(scene_captures.CaptureRefused) as caught:
            scene_captures.capture_open_scene(self.prefs, self.scene)
        self.assertIn("Detected: Karma CPU", str(caught.exception),
                      "in Debug Mode the message must name the delegate")

    def test_the_state_is_read_before_capturing(self):
        """Order, measured: the state is read before the capture, or reading it cannot avoid the stall."""
        order = []
        self.scene = _real_scene(self)
        _patch(self, scene_captures, "current_scene_path", lambda: self.scene)
        _patch(self, scene_captures, "viewport_state",
               lambda *a: order.append("state") or {"blocking": False})
        _patch(self, scene_captures, "capture_viewport",
               lambda out, viewer=None: order.append("capture") or out)
        scene_captures.capture_open_scene(self.prefs, self.scene)
        self.assertEqual(["state", "capture"], order)

    def test_it_refuses_rather_than_offering_to_proceed(self):
        """No capture-anyway offer: the replaced capture_viewport fails the test if it runs."""
        self._blocking()
        with self.assertRaises(scene_captures.CaptureRefused) as caught:
            scene_captures.capture_open_scene(self.prefs, self.scene)
        self.assertNotIn("anyway", str(caught.exception).lower())

    def test_a_tile_capture_is_refused_the_same_way(self):
        """Every tile capture grabs the Scene View, so every one reads its state first."""
        self._blocking()
        landed = []

        def heard(key):
            landed.append(key)

        captures.signals.landed.connect(heard)
        self.addCleanup(captures.signals.landed.disconnect, heard)
        with self.assertRaises(scene_captures.CaptureRefused):
            scene_captures.capture_tile(tile_icons.thumbnail_path(
                self.prefs, "abc", "materials.json"), "abc")
        self.assertEqual([], landed, "a refused capture still emitted `landed`")


class TileCropTest(unittest.TestCase):
    """A wide capture fills the tile and is cropped, rather than letterboxed with empty bands."""

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
        """Checks the test itself: cover and contain must produce different pixmaps."""
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
            import time
            from PySide6 import QtCore
            role = QtCore.Qt.ItemDataRole.DecorationRole
            deadline = time.time() + 5.0
            while time.time() < deadline and any(    # a paint requests the image from the engine; CropRole reads the result
                    thumbnails.engine.is_pending(("capture", model.capture_path(i)))
                    or model.data(model.index(i, 0), role) is None for i in range(4)):
                QtWidgets.QApplication.processEvents()
                time.sleep(0.005)
            return [bool(model.data(model.index(i, 0), model.CropRole)) for i in range(4)]

        self.assertEqual([False, False, False, False], crops(),
                         "a row with no capture crops its square picture")
        _write_png(model.capture_path(0), _two_tone_png_bytes())
        captures.announce(model.tile_key(0))    # as a capture does: the cached missing state is cleared
        self.assertEqual([True, False, False, False], crops(),
                         "a scene showing its capture does not fill the tile")
        _write_png(model.capture_path(1), _two_tone_png_bytes())
        captures.announce(model.tile_key(1))
        self.assertEqual([True, True, False, False], crops(),
                         "an image showing its capture does not fill the tile")
        model.tile_icon = lambda row: {"face": "generic"} if row == 0 else {}
        self.assertEqual([False, True, False, False], crops(),
                         "a scene showing its generic face still crops")


class OpenSceneBadgeTest(unittest.TestCase):
    """The tile of the scene open in Houdini shows a badge."""

    def setUp(self):
        self.tmp = _Tmp(self)
        self.a = self.tmp.touch("a.hiplc")
        self.b = self.tmp.touch("b.hiplc")
        self.model = file_library.FileFiles(_Prefs([self.tmp.dir]))
        files_actions.connect(self.model, file_library.FileFolders(self.model.preferences))    # as the panel does
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
        """A scene opened by File > Open still gets the badge: it marks the scene open in Houdini."""
        from amaze.helpers import hostos
        scene_captures.current_scene_path = \
            lambda: hostos.canonical_path_key(self.b)
        self.assertEqual([False, True], self._flags())


class IconAssetsTest(unittest.TestCase):
    """Icons are looked up by filename at paint time, so a missing one silently paints no badge."""

    def _ui(self, name):
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "ui", name)

    def test_the_shipped_icons_exist(self):
        for name in ("badge_open.svg", "badge_favourite.svg",  # a missing badge paints nothing
                     "badge_versions.svg", "badge_comment.svg",
                     "badge_execute.svg", "badge_execute_hover.svg", "badge_execute_press.svg",
                     "icon_screenshot.svg", "logo.svg"):
            self.assertTrue(os.path.isfile(self._ui(name)),
                            "ui/%s is missing" % name)

    BUTTON_ICONS = ("icon_library.svg", "icon_renderer.svg",  # consumed by IconMenuButton/ChipToggleButton, which generate hover and pressed themselves
                    "icon_view.svg", "icon_screenshot.svg",
                    "grid.svg", "list.svg", "favourite.svg", "favourite_on.svg")

    def test_button_icons_ship_one_state_only(self):
        """A toolbar icon has bare artwork, no ids or hidden state layers; the button draws states."""
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
        """A toolbar icon's ink fills its viewBox like its neighbours', so it reads the same size."""
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
        """Checks the test itself: with a renamed asset the assertions above check nothing."""
        present = [n for n in self.BUTTON_ICONS
                   if os.path.isfile(self._ui(n))]
        self.assertGreaterEqual(
            len(present), 6,
            "only %d of the listed button icons exist - the convention "
            "check is inspecting almost nothing" % len(present))

    def test_the_badge_family_shares_a_dark_backdrop(self):
        """The four badges share one dark backdrop and each draws in two colours or more; no hex named."""
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
        """Every rest SVG is drawn at the rest opacity; the hover opacity applies to its icon only."""
        from amaze import amazetheme
        from amaze.helpers import ui_helpers
        from amaze.panel import delegates
        arts = sorted({b.off_art for b in delegates.BADGES if b.off_art}
                      | {b.art for b in delegates.BADGES if b.dims})
        self.assertEqual(["badge_comment_off", "badge_favourite_off", "badge_versions"], arts)
        backdrop = r'<path[^>]*?id="Rounded-Rectangle[^"]*"[^>]*?>'
        for art in arts:
            self.assertTrue(self._paths(art + ".svg"), "%s draws nothing" % art)
            with open(self._ui(art + ".svg"), encoding="utf-8") as fh:
                text = fh.read()
            drawn = {float(v) for _k, v in re.findall(
                r'((?:fill|stroke)-opacity)[=:]"?([0-9.]+)', text)}
            self.assertEqual({amazetheme.BADGE_REST_OPACITY}, drawn,    # exported from the rest frames
                             "%s is not drawn at the rest opacity the code paints" % art)
            rest = ui_helpers.at_opacity(text, amazetheme.BADGE_REST_OPACITY)
            hover = ui_helpers.at_opacity(text, amazetheme.BADGE_HOVER_OPACITY)
            self.assertNotEqual(self._paint_of(rest), self._paint_of(hover),
                                "%s looks the same at rest and under the pointer" % art)
            self.assertEqual(re.findall(backdrop, text, re.S), re.findall(backdrop, hover, re.S),
                             "%s changed its backdrop under the pointer" % art)
            alphas = {float(v) for _k, v in re.findall(
                r'((?:fill|stroke)-opacity)[=:]"?([0-9.]+)', re.sub(backdrop, "", hover, flags=re.S))}
            self.assertEqual({amazetheme.BADGE_HOVER_OPACITY}, alphas,
                             "%s has an icon part the hover opacity does not change" % art)
        self.assertTrue(self._paths("badge_favourite.svg"),
                        "the favourite state draws nothing")

    def test_a_hover_art_keeps_the_ground_and_colours_the_icon(self):
        """On hover the background keeps the rest opacity and the icon gets its colour."""
        from amaze import amazetheme
        from amaze.panel import delegates
        pairs = [(b.off_art, b.off_hover_art) for b in delegates.BADGES if b.off_hover_art]
        pairs += [(b.art, b.hover_art) for b in delegates.BADGES if b.dims and b.hover_art]
        self.assertEqual(3, len(pairs), "the three outline button badges do not all colour on hover")
        for rest, hover in pairs:
            with open(self._ui(hover + ".svg"), encoding="utf-8") as fh:
                text = fh.read()
            ground = re.search(r'<path[^>]*?id="Rounded-Rectangle[^"]*"[^>]*?>', text, re.S)
            self.assertIsNotNone(ground, "%s has no background" % hover)
            self.assertEqual(("#000000", amazetheme.BADGE_REST_OPACITY),
                             self._effective_paint(ground.group(0)),
                             "%s changed its background" % hover)
            inks = {ink.upper() for ink in re.findall(r'stroke="(#[0-9A-Fa-f]{6})"', text)}
            self.assertTrue(inks, "%s draws no icon" % hover)
            self.assertNotIn("#FFFFFF", inks, "%s keeps %s's white icon" % (hover, rest))

    def test_the_run_button_keeps_its_shape_and_changes_its_paint(self):
        """Rest, hover and press draw one shape; only the play mark's colour differs. ▸r/tile-from-frame"""
        rest = self._paths("badge_execute.svg")
        self.assertTrue(rest, "the run button draws nothing")
        for state in ("badge_execute_hover.svg", "badge_execute_press.svg"):
            drawn = self._paths(state)
            self.assertEqual(len(rest), len(drawn),
                             "%s draws a different number of parts" % state)
            self.assertEqual(rest, drawn,
                             "%s changed the backdrop's or the play mark's shape" % state)
        paints = {self._paint(name).__repr__() for name in (
            "badge_execute.svg", "badge_execute_hover.svg", "badge_execute_press.svg")}
        self.assertEqual(3, len(paints), "two of the run button's states look the same")

    @staticmethod
    def _effective_paint(tag):
        """A tag's painted fill and fill-opacity: `style` overrides attributes. ▸r/svg-style-wins"""
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
        """Every badge file, in every state, has the design's one backdrop: black at one strength."""
        names = sorted(name[:-len(".svg")] for name in os.listdir(self._ui(""))
                       if name.startswith("badge_") and name.endswith(".svg"))
        self.assertIn("badge_execute_press", names)
        expected_alpha = dict.fromkeys(names, 0.75)
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
                msg="ui/%s.svg's backdrop opacity differs from the delivered "
                    "design" % name)

    def _paths(self, name):
        """The drawn geometry of an SVG: every path's `d`, in order."""
        with open(self._ui(name), encoding="utf-8") as fh:
            return re.findall(r'\sd="([^"]+)"', fh.read())

    def _paint(self, name):
        """How the geometry is painted: fills, strokes, opacities, style attributes. ▸r/svg-style-wins"""
        with open(self._ui(name), encoding="utf-8") as fh:
            return self._paint_of(fh.read())

    @staticmethod
    def _paint_of(text):
        return re.findall(r'((?:fill|stroke)(?:-opacity)?|opacity|style)="([^"]+)"', text)


class CaptureButtonTest(unittest.TestCase):
    """The capture button's place in the toolbar, read off the constructed layout of a real panel."""

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
        """The whole row in the designed order, each control by its own distinct objectName."""
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
             "btn_hip_capture", "btn_generate", "btn_prefs"],
            row,
            "the toolbar row is not in the designed order")


class SectionRegistrationTest(unittest.TestCase):
    """Scene rows are in the File section since the merge; these registration checks cover it."""

    def test_the_file_section_is_registered(self):
        keys = [cls.key for cls in sections.SECTION_CLASSES]
        self.assertIn("file", keys)
        self.assertNotIn("hip", keys,
                         "the HIP tab is back beside the File section "
                         "that replaced it")

    def test_it_points_at_models_the_panel_builds(self):
        """Each attribute name is looked up on the panel at runtime, so a typo shows only on click."""
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
    """capture_open_scene makes every refusal and never uses hou.ui, so these run headless."""

    def setUp(self):
        self.prefs = _library_prefs(self)

    def test_no_open_scene_is_refused_with_a_reason(self):
        _patch(self, scene_captures, "current_scene_path", lambda: "")
        with self.assertRaises(scene_captures.CaptureRefused) as caught:
            scene_captures.capture_open_scene(self.prefs)
        self.assertIn("nothing to capture", str(caught.exception).lower())

    def test_a_target_that_is_not_open_is_refused(self):
        self.scene = _real_scene(self)
        _patch(self, scene_captures, "current_scene_path", lambda: self.scene)
        with self.assertRaises(scene_captures.CaptureRefused) as caught:
            scene_captures.capture_open_scene(self.prefs, _real_scene(self, "other.hiplc"))
        self.assertIn("different scene", str(caught.exception))

    def test_a_rendering_viewport_is_refused(self):
        self.scene = _real_scene(self)
        _patch(self, scene_captures, "current_scene_path", lambda: self.scene)
        _patch(self, scene_captures, "viewport_state",
               lambda *a: {"blocking": True, "renderer": "Karma CPU"})
        _patch(self, scene_captures, "capture_viewport",
               lambda out, viewer=None: self.fail("captured through a renderer"))
        with self.assertRaises(scene_captures.CaptureRefused) as caught:
            scene_captures.capture_open_scene(self.prefs, self.scene)
        self.assertIn("stop the viewport render", str(caught.exception))

    def test_the_guard_and_the_capture_get_the_SAME_viewport(self):
        """The viewport is resolved once for guard and capture; each call here returns a new object."""
        handed = []
        viewers = iter(["FIRST", "SECOND", "THIRD"])
        self.scene = _real_scene(self)
        _patch(self, scene_captures, "current_scene_path", lambda: self.scene)
        _patch(self, scene_captures, "scene_viewer", lambda: next(viewers))
        _patch(self, scene_captures, "viewport_state",
               lambda v=None: handed.append(("guard", v))
               or {"blocking": False})
        _patch(self, scene_captures, "capture_viewport",
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
        """The shelf tool captures whatever scene is open, including one Amaze did not open."""
        taken = []
        self.scene = _real_scene(self, "manual.hiplc")
        _patch(self, scene_captures, "current_scene_path", lambda: self.scene)
        _patch(self, scene_captures, "viewport_state", lambda *a: {"blocking": False})
        _patch(self, scene_captures, "capture_viewport",
               lambda out, viewer=None: taken.append(out) or out)
        out = scene_captures.capture_open_scene(self.prefs)
        expected = captures.file_path(self.prefs, captures.file_key(self.prefs, self.scene))
        self.assertEqual([expected], taken, "the open scene's capture went somewhere else")
        self.assertEqual(expected, out)

    def test_no_panel_entry_point_re_decides(self):
        """Read from source: every capture entry point leaves the checks to scene_captures."""
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "panel", "tile_capture.py")
        with open(path, encoding="utf-8") as handle:
            code = handle.read()
        for name, shared in (("from_toolbar", ("onto_tile(", "capture_and_report(")),
                             ("onto_tile", ("capture_tile(", "capture_and_report(")),
                             ("capture_and_report", ("capture_open_scene(",))):
            start = code.find("def %s" % name)
            self.assertGreater(start, -1, "%s is gone" % name)
            end = code.find("\n    def ", start + 10)
            body = re.sub(r"#.*", "", code[start:end if end > 0 else len(code)])
            for call in shared:
                self.assertIn(call, body, "%s does not use the shared path" % name)
            for owned in ("viewport_state(", "displayMessage(", "capture_viewport("):    # unguarded
                self.assertNotIn(
                    owned, body,
                    "%s repeats a check with %s - that belongs to "
                    "scene_captures only" % (name, owned))


class CaptureRefreshesTheTileTest(unittest.TestCase):
    """A capture itself drops the engine's decoded copy, so the tile refreshes for every caller."""

    def test_the_whole_chain_repaints_the_right_row(self):
        """End to end: emit -> _on_capture_landed -> the matching file_key's row dropped, repainted."""
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

    def test_the_capture_path_is_wired_to_the_models(self):
        """Read from source: a capture is announced once written; both model classes listen."""
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
                           "the capture is announced BEFORE it is written")
        for module in ("file_library.py", "library.py"):
            self.assertIn("captures.signals.landed.connect(", read(module),
                          "%s does not listen for a capture" % module)


class CaptureBlankFrameAndRefusalPinsTest(unittest.TestCase):
    """The blank-frame rule, an empty path, an unsaved scene, and a refusal naming the right scene."""

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
        _patch(self, scene_captures, "current_scene_path", lambda: "/nope/untitled.hip")
        _patch(self, scene_captures, "capture_viewport", lambda out, viewer=None: self.fail(
            "captured a scene that is not on disk"))
        with self.assertRaises(scene_captures.CaptureRefused) as caught:
            scene_captures.capture_open_scene(_library_prefs(self))
        self.assertIn("not been saved", str(caught.exception))

    def test_the_refusal_does_not_claim_a_different_scene_wrongly(self):
        """The refusal never claims a different scene when the viewport shows this one."""
        tmp = _Tmp(self)
        scene = tmp.touch("open.hiplc")
        _patch(self, scene_captures, "current_scene_path", lambda: scene)
        _patch(self, scene_captures, "viewport_state", lambda *a: {"blocking": False})
        _patch(self, scene_captures, "scene_viewer", lambda: "V")
        _patch(self, scene_captures, "capture_viewport", lambda out, viewer=None: out)
        scene_captures.capture_open_scene(_library_prefs(self), scene)      # must NOT raise


class AnyViewerContextCanBeCapturedTest(unittest.TestCase):
    """Every context captures, COP too: browsing a copnet, the Scene View is still a 3D viewport."""

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

    def _capture_from(self, category):
        scene = _real_scene(self)
        _patch(self, scene_captures, "current_scene_path", lambda: scene)
        _patch(self, scene_captures, "scene_viewer", lambda: self._Viewer(category))
        _patch(self, scene_captures, "viewport_state", lambda *a: {"blocking": False})
        _patch(self, scene_captures, "capture_viewport", lambda out, viewer=None: "/tmp/shot.png")
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
    """The shelf ships with the package: Houdini cannot bind a key to a Python Panel action."""

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
        self.assertEqual(["amaze_capture_hip", "amaze_check_updates",  # the whole set, listed: a count would pass a rename or a duplicate
                          "amaze_open_panel", "amaze_reload", "amaze_repair_library"], names)

    def test_every_tool_is_on_the_shelf_tab(self):
        """Only the repo's part: the dock fills from shelf sets, which are a per-machine step."""
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
        package = os.path.dirname(self._shelf_path())  # $AMAZE is the repo or install root, so the icon path resolves from there
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

    def test_the_pane_tab_wears_the_mark_the_shelf_tool_wears(self):
        """One icon for Amaze: the pypanel icon is the open-panel tool's file, not the stock Python one."""
        import xml.etree.ElementTree as ET
        tool = [t for t in self._shelf().findall("tool") if t.get("name") == "amaze_open_panel"][0]
        pypanel = os.path.join(os.path.dirname(self._shelf_path()), "..",
                               "python_panels", "Amaze.pypanel")
        interface = ET.parse(pypanel).getroot().find("interface")
        self.assertEqual(tool.get("icon"), interface.get("icon"))

    ONE_CALL = {"amaze_capture_hip": "capture", "amaze_check_updates": "check_for_updates",
                "amaze_reload": "reload_asset_files"}

    def _script(self, name):
        return [t for t in self._shelf().findall("tool")
                if t.get("name") == name][0].find("script").text or ""

    def _refused_imports(self, refused):
        """Each import `refused(module, names)` answers True for raises ImportError("probe")."""
        import builtins
        from unittest import mock
        real = builtins.__import__

        def importing(name, globals=None, locals=None, fromlist=(), level=0):
            if refused(name, fromlist or ()):
                raise ImportError("probe")
            return real(name, globals, locals, fromlist, level)
        return mock.patch.object(builtins, "__import__", importing)

    def _dialogs(self):
        """A host ui recording each message box and status line, and the patch putting it in."""
        import types
        from unittest import mock
        import hou
        said, bar = [], []
        ui = types.SimpleNamespace(
            displayMessage=lambda text, **kwargs: said.append(text) or 0,
            setStatusMessage=lambda text, **kwargs: bar.append(text))
        return said, bar, mock.patch.object(hou, "ui", ui, create=True)

    def test_capture_updates_and_reload_are_one_call_each(self):
        """The shelf keeps the import and one call; what a tool does is code the suite runs."""
        from amaze.utils import rc_calls
        for name, function in self.ONE_CALL.items():
            with self.subTest(name):
                code = [line.strip() for line in self._script(name).splitlines()
                        if line.strip() and not line.strip().startswith("#")]
                self.assertEqual(
                    ["import hou", "from amaze.utils import rc_calls"],
                    [line for line in code if line.startswith(("import ", "from "))])
                self.assertEqual("rc_calls.%s()" % function, code[-1])
                self.assertTrue(callable(getattr(rc_calls, function, None)),
                                "the shelf calls a function rc_calls does not have")

    def test_a_broken_install_says_what_messages_py_says(self):
        """The shelf's copy of the message, shown when rc_calls cannot load, matches messages.py."""
        from amaze import messages
        for name in self.ONE_CALL:
            with self.subTest(name):
                said, _bar, ui = self._dialogs()
                with ui, self._refused_imports(
                        lambda module, names: module == "amaze.utils" and "rc_calls" in names):
                    exec(compile(self._script(name), name, "exec"), {"__name__": name})
                self.assertEqual([messages.AMAZE_NOT_IMPORTABLE % "probe"], said)

    def test_each_function_says_it_too_when_its_own_imports_fail(self):
        from amaze import messages
        from amaze.utils import rc_calls
        for function in self.ONE_CALL.values():
            with self.subTest(function):
                said, _bar, ui = self._dialogs()
                with ui, self._refused_imports(lambda module, names: module.startswith("amaze")):
                    getattr(rc_calls, function)()
                self.assertEqual([messages.AMAZE_NOT_IMPORTABLE % "probe"], said)

    def test_capture_shows_a_refusal_and_reports_a_capture(self):
        """The panel button's capture: a refusal is a dialog, a capture a line in the status bar."""
        from unittest import mock
        import hou
        from amaze.core import scene_captures
        from amaze.prefs import prefs as prefs_module
        from amaze.utils import rc_calls
        said, bar, ui = self._dialogs()
        with ui, mock.patch.object(prefs_module.Prefs, "load", return_value=True):
            with mock.patch.object(scene_captures, "capture_open_scene",
                                   side_effect=scene_captures.CaptureRefused("refused")):
                rc_calls.capture()
            with mock.patch.object(scene_captures, "capture_open_scene", return_value="x.png"):
                rc_calls.capture()
        self.assertEqual(["refused"], said)
        self.assertEqual(["Amaze: thumbnail captured for %s" % hou.hipFile.basename()], bar)

    def test_the_panel_tool_names_the_real_interface(self):
        root = self._shelf()
        tool = [t for t in root.findall("tool")
                if t.get("name") == "amaze_open_panel"][0]
        script = tool.find("script").text or ""
        self.assertIn("interfaceByName", script)
        import re as _re
        asked = _re.search(r'^INTERFACE\s*=\s*[\'"]([^\'"]+)', script, _re.M)  # cross-references the two files: separate literal checks are no comparison
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
        """createFloatingPaneTab takes the interface name; the interface object raises TypeError."""
        root = self._shelf()
        tool = [t for t in root.findall("tool")
                if t.get("name") == "amaze_open_panel"][0]
        script = tool.find("script").text or ""
        start = script.find("desktop.createFloatingPaneTab")  # the call, not the word, which a comment may also carry
        self.assertGreater(start, -1, "the tool no longer opens a panel")
        depth = 0  # balance the parentheses, or the first close cuts the asserted argument short
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
        assigned = _re.search(r'^INTERFACE\s*=\s*(.+)$', script, _re.M)  # INTERFACE must be a name, not interfaceByName's object, which raises TypeError
        self.assertIsNotNone(assigned, "INTERFACE is never assigned")
        self.assertRegex(
            assigned.group(1).strip(), r'^[\'"][^\'"]+[\'"]$',
            "INTERFACE is not a string literal, so the API is handed "
            "an object again")

    def test_the_panel_tool_always_opens_a_new_window(self):
        """Every activation opens a new floating panel; no branch raises an open one instead."""
        root = self._shelf()
        tool = [t for t in root.findall("tool")
                if t.get("name") == "amaze_open_panel"][0]
        script = re.sub(r"#.*", "", tool.find("script").text or "")  # CODE only: a comment explaining why there is no such branch must not itself read as the branch
        for spelling in ("paneTabs", "activeInterface", "setIsCurrentTab",
                         "floatingPanel", "raise_", "activateWindow"):
            self.assertNotIn(
                spelling, script,
                "the tool looks for an open Amaze again (%s) - an "
                "activation that raises a window opens no new one" % spelling)
        help_text = tool.find("helpText").text or ""
        for promise in ("raises", "already open"):
            self.assertNotIn(
                promise, help_text,
                "the help still promises to raise an open Amaze (%r), "
                "which the tool no longer does" % promise)

    def test_no_default_hotkey_is_shipped(self):
        """No default hotkey: a key chosen for the user may already mean something."""
        with open(self._shelf_path(), encoding="utf-8") as handle:
            body = handle.read()
        self.assertNotIn("<hotkey", body.lower())

    def _run_reload(self, houdini_spelling):
        """Run the Reload tool against one package holding one asset; returns it and the calls made."""
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
        self.bar = []
        fake.ui = types.SimpleNamespace(
            setStatusMessage=lambda text, **kwargs: self.bar.append(text),
            displayMessage=lambda *a, **k: 0)
        fake.severityType = types.SimpleNamespace(Message="message")
        tool = [t for t in self._shelf().findall("tool")
                if t.get("name") == "amaze_reload"][0]
        from amaze.utils import rc_calls
        with mock.patch.dict(sys.modules, {"hou": fake}), \
                mock.patch.object(rc_calls, "hou", fake):    # the function's own hou, not the script's
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
        self.assertEqual(["Amaze: 0 asset files reloaded, 1 new"], self.bar)

    def test_sync_install_carries_the_toolbar(self):
        """The sync copies the toolbar folder, or that shipped file only exists in the repo."""
        tools = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))),
            "tools", "sync-install.sh")
        with open(tools, encoding="utf-8") as handle:
            body = handle.read()
        self.assertIn('amaze_mirror "$repo/toolbar"', body,  # the shared resolver copies through amaze_mirror, not rsync
                      "sync-install.sh does not copy the toolbar")
        self.assertIn('diff -rq "$repo/toolbar"', body,
                      "the sync does not VERIFY the toolbar was copied")


class LibraryUpdateTest(unittest.TestCase):
    """Opening a library updates its recorded version to this Amaze's at once, without asking."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def setUp(self):
        import types
        from unittest import mock
        from amaze.core import library_policy, library_settings
        self.policy, self.settings = library_policy, library_settings
        self.dir = self.panel.prefs.dir
        test_support.set_library_version(self.dir, 3)    # a library a step-1 Amaze stamped
        test_support.reset_database_singletons()
        self.asked = []
        ui = types.SimpleNamespace(displayMessage=lambda *a, **k: self.asked.append(a) or 0)
        patcher = mock.patch.object(hou, "ui", ui, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_version_moves_without_a_question(self):
        """No Later: a library is never left open but not updated."""
        self.panel._update_library()
        self.assertEqual(self.policy.LIBRARY_VERSION, self.settings.library_version(self.dir))
        self.assertEqual([], self.asked, "the update asked first")

    def test_an_open_preferences_window_shows_the_new_version(self):
        """Reload Library runs the update under an open Preferences, which kept the old number."""
        self.panel.show_prefs()
        dialog = self.panel._prefs_dialog
        self.addCleanup(dialog.close)
        self.assertEqual("Format: v3", dialog._lbl_library_format.text())
        self.panel._update_library()
        self.assertEqual("Format: v2.0", dialog._lbl_library_format.text())


class NewerLibraryTest(unittest.TestCase):
    """A library a newer Amaze updated stays closed, and the update that opens it is offered."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def setUp(self):
        from amaze.core import library_policy, library_settings
        self.policy = library_policy
        self.dir = self.panel.prefs.dir
        self.newer = library_policy.LIBRARY_VERSION + 1
        before = library_settings.library_version(self.dir)
        test_support.set_library_version(self.dir, self.newer)
        self.addCleanup(test_support.set_library_version, self.dir, before)
        test_support.reset_database_singletons()

    def _answering(self, choice):
        import types
        from unittest import mock
        asked = []
        ui = types.SimpleNamespace(
            displayMessage=lambda text, **kwargs: asked.append((text, kwargs)) or choice)
        patcher = mock.patch.object(hou, "ui", ui, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        return asked

    def _idle(self, asked):
        for _ in range(20):
            QtWidgets.QApplication.processEvents()
            if asked:
                break

    def test_a_panel_opened_on_it_stays_without_a_library(self):
        asked = self._answering(1)
        panel = test_support.reopened_panel(self)
        self.assertIsNone(panel.material_model, "the newer library was opened")
        self.assertEqual([], asked, "asked inside onCreateInterface, where a modal draws black")
        self._idle(asked)
        text, kwargs = asked[0]
        self.assertEqual("This library is version 2.1 and needs a newer Amaze. "
                         "Update Amaze to open it.", text)
        self.assertEqual(("Update Amaze", "Cancel"), tuple(kwargs["buttons"]))

    def test_a_switch_onto_it_leaves_the_models_where_they_are(self):
        from unittest import mock
        asked = self._answering(1)
        with mock.patch.object(type(self.panel.material_model), "switch_model_data") as switched:
            self.panel.open_library()
        switched.assert_not_called()
        self._idle(asked)
        self.assertEqual(1, len(asked), "the update was not offered")

    def test_a_switch_onto_it_puts_the_library_path_back(self):
        """The settings keep naming the open library: else every later save is refused."""
        asked = self._answering(1)
        other = test_support.seeded_library(self)
        test_support.set_library_version(other, self.newer)
        before = self.panel.prefs.dir
        self.addCleanup(setattr, self.panel.prefs, "dir", before)    # the class shares one panel
        self.panel.prefs.dir = other    # what Reload or closing Preferences reads back
        self.assertFalse(self.panel.open_library())
        self._idle(asked)
        self.assertEqual(before, self.panel.prefs.dir,
                         "the Library Path names a library that stayed closed")

    def test_update_amaze_installs_the_newest_release(self):
        from unittest import mock
        from amaze.core import updater
        from amaze.dialogs import update_dialog
        asked = self._answering(0)
        found = updater.Update(updater.NEWER, version="9.9", url="https://example.invalid/r.zip",
                               sentence="newer", library_version=self.newer)
        with mock.patch.object(updater, "check", return_value=found), \
                mock.patch.object(update_dialog, "install_and_say") as install:
            self.panel._offer_amaze_update()
        install.assert_called_once_with(found)
        self.assertEqual(1, len(asked), "a release reading this library asked Continue too")


class AssetCaptureTest(unittest.TestCase):
    """Any library tile can show a capture, kept as its one picture `materials/<id>.png`."""

    def setUp(self):
        from amaze.core import library
        self.prefs = test_support.fixture_prefs(self)
        self.model = library.MaterialLibrary(self.prefs)
        self.assertGreater(self.model.rowCount(), 0, "the fixture library is empty")

    def test_the_capture_is_kept_under_the_asset_id(self):
        self.assertEqual(os.path.join(str(self.prefs.dir), "materials",
                                      self.model.tile_key(0) + ".png"),
                         self.model.capture_path(0))
        self.assertEqual(tile_icons.thumbnail_path(self.prefs, self.model.tile_key(0),
                                                   self.model.DB_FILENAME),
                         self.model.capture_path(0))

    def test_the_image_face_reads_the_one_picture_and_fills_the_tile(self):
        """Render or capture, the tile reads one file; Image crops, the other faces do not."""
        self.assertEqual(self.model.capture_path(0), self.model._mat_paths[0],
                         "the tile reads another file than a capture writes")
        self.assertTrue(self.model.data(self.model.index(0, 0), self.model.CropRole))
        self.assertTrue(self.model.set_tile_icon(0, {"face": "generic"}))
        self.addCleanup(self.model.set_tile_icon, 0, {})
        self.assertFalse(self.model.data(self.model.index(0, 0), self.model.CropRole),
                         "a generic face still crops")
        self.assertEqual(self.model.capture_path(0), self.model._mat_paths[0])

    def test_a_landed_capture_repaints_the_asset(self):
        self.model.set_tile_icon(0, {"face": "image"})
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
        owned = self.model.asset_files("abc")
        self.assertEqual(tile_icons.thumbnail_path(self.prefs, "abc", self.model.DB_FILENAME),
                         owned["thumbnail"])
        self.assertEqual([], sorted(set(owned) & {"capture", "tile_icon"}),
                         "an asset still owns a second picture")

    def test_a_capture_replaces_the_picture_customize_shows(self):
        row = next(row for row in range(self.model.rowCount())
                   if os.path.exists(self.model.capture_path(row)))    # a row with a render
        before = self.model.preview_image(row)
        self.assertIsNotNone(before, "premise: the fixture asset has a render")
        self.assertNotEqual((4, 4), (before.width(), before.height()))
        _write_png(self.model.capture_path(row), _two_tone_png_bytes())
        after = self.model.preview_image(row)
        self.assertIsNotNone(after)
        self.assertEqual((4, 4), (after.width(), after.height()),
                         "the capture did not replace the render in place")


class CaptureFromTheMenuTest(unittest.TestCase):
    """Capture on the right-click menu and the toolbar, driven on a real panel."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _select(self, key, rows):
        """Show section `key` with `rows` selected; returns its context and the selection."""
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
        context = panel.active_section()
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
        _patch(self, self.panel.tile_capture, "report_refused", said.append)
        return said

    def test_one_tile_in_any_section_can_be_captured(self):
        for key in ("material", "code", "gradient"):
            with self.subTest(section=key):
                context, chosen = self._select(key, [0, 1])
                self.assertTrue(context.menu_capture_enabled(chosen[:1], chosen[0]))
                self.assertFalse(context.menu_capture_enabled(chosen, chosen[0]),
                                 "one capture was offered for two tiles")

    def test_a_scene_is_captured_only_while_it_is_the_open_one(self):
        rows = self._rows_of_kind(locations.KIND_HIP)
        context, chosen = self._select("file", rows[:1])
        path = chosen[0].data(self.panel.file_files_model.PathRole)
        _patch(self, scene_captures, "current_scene_path", lambda: "")
        self.assertFalse(context.menu_capture_enabled(chosen, chosen[0]),
                         "a scene that is not open was offered a capture")
        _patch(self, scene_captures, "current_scene_path", lambda: path)
        self.assertTrue(context.menu_capture_enabled(chosen, chosen[0]))

    def test_any_other_file_takes_a_capture(self):
        rows = self._rows_of_kind(locations.KIND_IMAGE)
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

        _patch(self, scene_captures, "capture_tile", capture)
        self.addCleanup(model.set_tile_icons, [row], {})
        self.panel.tile_capture.onto_tile(context, chosen[0])
        self.assertEqual([(model.capture_path(row), model.tile_key(row))], taken)
        self.assertEqual("image", tile_icons.face_for(model, row),
                         "the tile does not show the captured picture")

    def test_every_kind_of_asset_tile_paints_its_capture(self):
        """Code and Color paint their own pictures in RAM; a capture's file takes precedence."""
        for name in ("material_model", "code_model", "gradient_model"):    # the fixture has no Nodes
            with self.subTest(model=name):
                model = getattr(self.panel, name)
                self.assertGreater(model.rowCount(), 0, "the fixture has no %s rows" % name)
                _write_png(model.capture_path(0), _two_tone_png_bytes())
                self.addCleanup(model.set_tile_icons, [0], {})
                self.assertTrue(model.set_tile_icon(0, {"face": "image"}))
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

        _patch(self, scene_captures, "capture_tile", refuse)
        said = self._refusals()
        self.panel.tile_capture.onto_tile(context, chosen[0])
        self.assertEqual(["Please stop the viewport render before capturing."], said)
        self.assertEqual(before, model.tile_icon(row), "a refused capture changed the tile")

    def test_the_toolbar_asks_for_one_tile(self):
        from amaze import messages
        self._select("material", [])
        said = self._refusals()
        _patch(self, scene_captures, "capture_tile",
               lambda out, key: self.fail("captured onto no tile"))
        self.panel.tile_capture.from_toolbar()
        self.assertEqual([messages.CAPTURE_SELECT_ONE_TILE], said)

    def test_the_toolbar_in_File_with_nothing_selected_takes_the_open_scene(self):
        self._select("file", [])
        asked = []
        _patch(self, scene_captures, "capture_open_scene",
               lambda preferences, target="": asked.append(target) or "")
        self.panel.tile_capture.from_toolbar()
        self.assertEqual([""], asked, "the open scene was not captured")


class LoadOnTheGridMenuOpensTheSceneTest(unittest.TestCase):
    """File ▸ right-click a .hip ▸ Load, through the menu's own dispatch, reaches Houdini's load."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)

    def test_load_opens_the_row_it_was_picked_on(self):
        from unittest import mock
        from PySide6 import QtCore as _QtCore
        panel = self.panel
        panel.section_tabs.setChecked("file")
        QtWidgets.QApplication.processEvents()
        proxy = panel.thumblist.model()
        kind, path_role = panel.file_files_model.KindRole, panel.file_files_model.PathRole
        row = next((r for r in range(proxy.rowCount())
                    if proxy.index(r, 0).data(kind) == locations.KIND_HIP), None)
        self.assertIsNotNone(row, "premise: the fixture folder lists no scene")
        flags = _QtCore.QItemSelectionModel.SelectionFlag
        panel.thumblist.selectionModel().select(proxy.index(row, 0), flags.ClearAndSelect)
        loaded = []

        def _pick(menu, *_args, **_kwargs):
            return next(a for a in menu.actions() if a.text() == "Open Scene")

        with mock.patch.object(QtWidgets.QMenu, "exec_", _pick), \
                mock.patch.object(hou.hipFile, "load",
                                  lambda path, **_kwargs: loaded.append(path)):
            panel.active_section().rc_menu()
        self.assertEqual([proxy.index(row, 0).data(path_role)], loaded,
                         "Open Scene did not open the scene it was picked on")


class SectionListIsSingleSourcedTest(unittest.TestCase):
    """Every list of sections comes from one place, or a toggle omits a section the list lacks."""

    def test_every_registered_section_is_offered(self):
        listed = section_list.keys()
        registered = [c.key for c in sections.SECTION_CLASSES]
        self.assertEqual(registered, listed)
        self.assertIn("file", listed)

    def test_every_section_has_a_label(self):
        for key, label in section_list.SECTIONS:
            self.assertTrue(label, "section %r has no label" % key)

    def test_no_hardcoded_section_list_is_INCOMPLETE(self):
        """Source-derived: any literal section list in the tree must name every registered section."""
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
                        continue            # not a section list: the check requires another current section key
                    if "deliberately partial" in \
                            body[max(0, match.start() - 400):match.start()]:
                        continue            # a list allowed to be incomplete says so where it is declared
                    missing = keys - listed
                    if missing:
                        offenders.append(
                            "%s: missing %s"
                            % (os.path.relpath(path, root), sorted(missing)))
        self.assertEqual(
            [], offenders,
            "a section list omits a registered section - that is how "
            "the HIP tab was deleted: %s" % offenders)


class CheckLibraryConfirmsBeforeChangingTest(unittest.TestCase):
    """Source-derived: every action Check Library runs is confirmed first, Cancel on Return and Esc."""

    ACTIONS = ("repair.move_aside(", "repair.recover(",
               "repair.put_back(", "repair.set_aside_folders(", "repair.drop_dead_stars(",
               "repair.rescue_uncategorised(")
    GATES = ("_confirmed(", "**_copy_buttons(")

    def _source(self, *parts):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), *parts)
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def _bodies(self):
        code = self._source("dialogs", "repair_dialog.py")
        for chunk in code.split("\ndef ")[1:]:
            name = chunk.split("(", 1)[0]
            work = min((chunk.find(a) for a in self.ACTIONS if a in chunk), default=-1)
            if work > -1:
                yield name, chunk, work

    def test_it_confirms_before_doing_any_work(self):
        bodies = list(self._bodies())
        self.assertGreaterEqual(len(bodies), 6, "premise: the actions were not found")
        for name, body, work in bodies:
            with self.subTest(name=name):
                gate = min((body.find(g) for g in self.GATES if g in body), default=-1)
                self.assertGreater(gate, -1, "%s has no confirm" % name)
                self.assertLess(gate, work, "%s confirms AFTER the change" % name)

    def test_the_gate_can_be_cancelled(self):
        for name, body, work in self._bodies():
            with self.subTest(name=name):
                gate = min(body.find(g) for g in self.GATES if g in body)
                self.assertIn("return", body[gate:work], "%s cannot be stopped" % name)

    def test_cancel_is_the_default_and_the_close_action(self):
        """A gate that moves files must not act on Return or on Esc."""
        code = self._source("dialogs", "repair_dialog.py")
        confirm = code[code.find("def _confirmed("):code.find("\ndef ", code.find("def _confirmed("))]
        self.assertIn("default_choice=1", confirm)
        self.assertIn("close_choice=1", confirm)
        buttons = code[code.find("def _copy_buttons("):code.find("\ndef _put_copy_back(")]
        self.assertIn('"default_choice": len(buttons) - 1', buttons)
        self.assertIn('"close_choice": len(buttons) - 1', buttons)

    def test_it_does_not_announce_a_finish_with_nothing_to_say(self):
        self.assertNotIn("displayMessage(", self._source("actions", "check.py"))
        code = self._source("dialogs", "repair_dialog.py")
        start = code.find("def repair_found(")
        body = code[start:code.find("\ndef ", start)]
        self.assertTrue(body, "premise: the Repair dialog is gone")
        self.assertEqual(2, body.count("displayMessage("),
                         "the Repair dialog shows messages beyond what it found and what the fix did")


if __name__ == "__main__":
    unittest.main()
