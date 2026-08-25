"""The Conversion Engine: the DECODE/FIT split and the guard. The split: resampling while converting is a property of an image too big for Qt's allocation limit, never of a foreign format - `sips -Z` on a Radiance .hdr returns EXIT 0 and a solid black PNG, which turned 178 HDR tiles black with not one line in the log. The guard: an engine verifies its own output, an adapter is never trusted. A test for the guard would pass with the fix reverted and a test for the fix would pass with the guard removed - both are here."""

import inspect
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import conversion  # noqa: E402
from amaze.helpers import hostos  # noqa: E402


def write_radiance_hdr(path, width=256, height=128):
    """A real, readable Radiance .hdr - flat (uncompressed) RGBE. A FIXTURE, not a copy of the user's file: nothing in the suite may reach the machine's own images. The gradient matters - the failure this exists for produces a picture with no variation, so a flat fixture could not tell the two apart."""
    import math

    def rgbe(r, g, b):
        top = max(r, g, b)
        if top < 1e-32:
            return bytes((0, 0, 0, 0))
        mantissa, exponent = math.frexp(top)
        scale = mantissa * 256.0 / top
        return bytes((int(r * scale), int(g * scale), int(b * scale),
                      exponent + 128))

    with open(path, "wb") as fh:
        fh.write(b"#?RADIANCE\n")
        fh.write(b"FORMAT=32-bit_rle_rgbe\n\n")
        fh.write(b"-Y %d +X %d\n" % (height, width))
        for y in range(height):
            row = bytearray()
            for x in range(width):
                row += rgbe(0.2 + 3.0 * (x / width),
                            0.1 + 2.0 * (y / height),
                            0.5 + ((x + y) % 32) / 32.0)
            fh.write(bytes(row))
    return path


def write_png(path, width, height, flat=None):
    image = QtGui.QImage(width, height, QtGui.QImage.Format.Format_RGB32)
    if flat is not None:
        image.fill(QtGui.QColor(flat))
    else:
        for y in range(height):
            for x in range(0, width, 7):
                image.setPixelColor(
                    x, y, QtGui.QColor(x % 255, y % 255, (x + y) % 255))
    assert image.save(path, "PNG"), "could not write the fixture"
    return path


def uniform(image):
    return conversion._uniform(image)


OVERSIZED = (9000, 9000)  # 324MB decoded - big enough that the decode passes Qt's default 256MB limit


def qt_refuses(target, declared=OVERSIZED, only_first=False):
    """Make the Qt-native read refuse ONE file, declaring it oversized - how the FIT route is reached on purpose. Lowering `QImageReader.allocationLimit()` is NOT enough and the difference is a Qt version: on Qt 6.5.3 (H21) the limit applies to the WHOLE-image read only, so a scaled read of an oversized PNG simply loads, while Qt 6.8.3 (H22) refuses both - so this states the refusal and the declared size directly and the ENGINE's routing is under test on every Qt. `only_first=True` refuses the first file that is NOT `target` (a converter's own temp made to look oversized); `target=None` refuses everything."""
    real = conversion._read_qt
    state = {"chosen": None}

    def fake(path, size):
        if target is None and not only_first:
            return None, QtCore.QSize(*declared), "Unable to read image data"
        if only_first:
            if state["chosen"] is None and path != target:
                state["chosen"] = path
            hit = path == state["chosen"]
        else:
            hit = path == target
        if hit:
            return None, QtCore.QSize(*declared), "Unable to read image data"
        return real(path, size)

    return mock.patch.object(conversion, "_read_qt", fake)


class _StubSignal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)


class _StubProcess:
    """A killed child, scripted: dies inside the reap's half-second, or defers SIGKILL the way uninterruptible disk I/O does."""

    def __init__(self, reaps=True, running=True):
        self._reaps = reaps
        self._running = running
        self.killed = False
        self.deleted = False
        self.finished = _StubSignal()

    def state(self):
        running = QtCore.QProcess.ProcessState.Running
        gone = QtCore.QProcess.ProcessState.NotRunning
        return running if self._running else gone

    def kill(self):
        self.killed = True

    def waitForFinished(self, _ms):
        if self._reaps:
            self._running = False
            return True
        return False

    def program(self):
        return "/usr/bin/stub"

    def deleteLater(self):
        self.deleted = True


class TheGraveyardBoundsTheStall(unittest.TestCase):
    """A killed child that defers SIGKILL must cost its caller half a second, not the destructor's thirty: parked in the module graveyard, it collects itself when the kernel lets go - 71 deferred children once turned a 134s suite into 1211s and starved the thumbnail workers, the shape behind the hanging File-tab thumbnails."""

    def tearDown(self):
        conversion._ABANDONED.clear()

    def test_a_child_that_dies_in_time_is_simply_reaped(self):
        child = _StubProcess(reaps=True)
        self.assertTrue(conversion._reap_or_abandon(child))
        self.assertTrue(child.killed)
        self.assertEqual([], conversion._ABANDONED)

    def test_an_already_dead_child_needs_nothing(self):
        child = _StubProcess(running=False)
        self.assertTrue(conversion._reap_or_abandon(child))
        self.assertFalse(child.killed)

    def test_a_sigkill_deferring_child_is_abandoned_not_awaited(self):
        child = _StubProcess(reaps=False)
        self.assertFalse(conversion._reap_or_abandon(child))
        self.assertIn(child, conversion._ABANDONED)
        self.assertTrue(child.finished.slots,
                        "nothing collects the corpse later")
        child._running = False  # the kernel finally releases it: the slot must remove it from the graveyard and delete the Qt object
        child.finished.slots[0]()
        self.assertNotIn(child, conversion._ABANDONED)
        self.assertTrue(child.deleted)

    def test_a_child_dying_during_the_handover_is_still_collected(self):
        child = _StubProcess(reaps=False)
        original_wait = child.waitForFinished  # dead by the time the post-connect check runs - finished already fired and never comes again

        def wait_then_die(ms):
            result = original_wait(ms)
            child._running = False
            return result

        child.waitForFinished = wait_then_die
        self.assertFalse(conversion._reap_or_abandon(child))
        self.assertNotIn(child, conversion._ABANDONED)
        self.assertTrue(child.deleted)


class ACompletionReapedElsewhere(unittest.TestCase):
    """Qt hears a child exit through SIGCHLD, so a handler that auto-reaps steals the notification: the child is gone in milliseconds, the wait burns its WHOLE timeout, then parks a phantom in the graveyard - the production signature was 18 real files logged as timed out that convert in ~1s by hand. The cure under test: a liveness watchdog inside the wait - a pid that no longer exists while the state still reads Running can only mean the exit was reaped elsewhere, and a zombie keeps its pid until reaped, so the check cannot fire early on a healthy child."""

    @unittest.skipUnless(os.name == "posix", "SIGCHLD is POSIX-only")
    def test_a_reaped_child_returns_within_the_watchdog(self):
        import ctypes
        import signal as pysignal
        import time

        libc = ctypes.CDLL(None)
        libc.signal.restype = ctypes.c_void_p
        libc.signal.argtypes = [ctypes.c_int, ctypes.c_void_p]
        ok, err = conversion._run_process("/bin/echo", ["prime"],  # PRIME FIRST: Qt installs its child-exit handler on the first QProcess start, so a sabotage placed earlier is overwritten and the test passes for the wrong reason - unprimed, this ran green against the unfixed code
                                          timeout_ms=15000)
        self.assertTrue(ok, "the priming call itself failed: %r" % err)
        parked_before = len(conversion._ABANDONED)
        previous = libc.signal(int(pysignal.SIGCHLD), ctypes.c_void_p(1))
        try:
            start = time.monotonic()
            ok, err = conversion._run_process(
                "/bin/echo", ["reaped"], timeout_ms=6000)
            elapsed = time.monotonic() - start
        finally:
            libc.signal(int(pysignal.SIGCHLD),
                        ctypes.c_void_p(previous or 0))

        self.assertTrue(
            ok, "a child that ran to completion was reported as a "
                "failure: %r" % err)
        self.assertLess(
            elapsed, 3.0,
            "the wait burned its timeout on a child that had already "
            "exited (%.2fs)" % elapsed)
        self.assertEqual(
            parked_before, len(conversion._ABANDONED),
            "a phantom was parked in the graveyard - its destruction "
            "will stall shutdown")


class ConversionCase(unittest.TestCase):
    """Shared fixtures. Every path here is inside a temp dir."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_convert_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.hfs = os.environ.get("HFS", "")
        limit = QtGui.QImageReader.allocationLimit()
        self.addCleanup(QtGui.QImageReader.setAllocationLimit, limit)

    def path(self, name):
        return os.path.join(self.dir, name)

    def convert(self, path, size=256, **kw):
        kw.setdefault("hfs", self.hfs)
        return conversion.convert_image(path, size, **kw)


class TheDecodeFitSplit(ConversionCase):

    def test_a_radiance_hdr_keeps_its_picture(self):
        """The 178 black tiles, in one assertion - the OUTCOME. Held up by TWO independent things (the split and the verification), so putting `-Z` back on the FORMAT route leaves it GREEN: the engine refuses the black answer and iconvert carries the file - the design working, not a hole. What it pins is that a Radiance .hdr comes out of this engine with its picture, however achieved; each mechanism has its own test either side of this one, red on its own sabotage."""
        if not hostos.is_macos():
            self.skipTest("sips is macOS-only; the FORMAT route here is "
                          "iconvert, which never had this failure")
        hdr = write_radiance_hdr(self.path("sky.hdr"), 1024, 512)  # BIGGER than the thumbnail asked for, load-bearing: -Z 256 on a source already within 256px is a no-op and comes back correct; a 1024x512 fixture gives the same 1,675-byte black PNG the real library produced, a smaller one cannot reproduce this at all
        result = self.convert(hdr)
        self.assertTrue(
            result, "no thumbnail at all for a Radiance .hdr: %s"
                    % (result.reason,))
        self.assertFalse(
            uniform(result.image),
            "the .hdr converted to a single flat colour - this is the "
            "black-tile failure, back")
        self.assertFalse(result.uniform)

    def test_the_FORMAT_route_converts_and_does_not_resample(self):
        """The split itself, read off the command line that runs: `-Z` resamples WHILE converting - mandatory on the FIT route (a full-size temp is refused all over again) and what destroyed HDR on the FORMAT route, where a full-size temp is perfectly loadable and Qt scales it. One flag, two contracts - the moment a shared helper became two functions."""
        if not hostos.is_macos():
            self.skipTest("sips is macOS-only")
        hdr = write_radiance_hdr(self.path("sky.hdr"), 1024, 512)
        seen = []
        real = conversion._run_process

        def spy(program, args, **kw):
            seen.append((os.path.basename(program), list(args)))
            return real(program, args, **kw)

        with mock.patch.object(conversion, "_run_process", spy):
            self.convert(hdr)

        sips = [args for name, args in seen if name == "sips"]
        self.assertTrue(sips, "sips never ran for a foreign format")
        self.assertNotIn(
            "-Z", sips[0],
            "the FORMAT route resampled while converting - that is the "
            "one thing that turns a Radiance .hdr black: %s" % (sips[0],))

    def test_the_FIT_route_does_resample(self):
        """The other half: without this, deleting `-Z` everywhere passes the test above and quietly breaks every oversized image - the temp file is refused by Qt all over again."""
        if not hostos.is_macos():
            self.skipTest("sips is macOS-only")
        png = write_png(self.path("big.png"), 1200, 1200)
        seen = []
        real = conversion._run_process

        def spy(program, args, **kw):
            seen.append((os.path.basename(program), list(args)))
            return real(program, args, **kw)

        with qt_refuses(png):
            with mock.patch.object(conversion, "_run_process", spy):
                result = self.convert(png)

        self.assertTrue(result, "an oversized PNG got no thumbnail")
        sips = [args for name, args in seen if name == "sips"]
        self.assertTrue(sips, "sips never ran for an oversized image")
        self.assertIn(
            "-Z", sips[0],
            "the FIT route converted at full size - the temp file is "
            "then refused by Qt exactly like the source was: %s"
            % (sips[0],))

    def test_which_route_applies_is_measured_not_guessed(self):
        """No extension list, anywhere in the code: the old worker chose its decoder from the file NAME, which is how a format needing one route gets sent down the other - the engine measures the file instead. Read with `ast`, and only at CODE: a comment naming .hdr is history, and a rule that bans explaining yourself is worse than no rule; .png is exempt because the scratch file is a PNG, an output format and not a routing decision."""
        import ast

        FORMATS = {"exr", "hdr", "rat", "tga", "tif", "tiff", "jpg",  # undotted, so a literal is caught whichever form it is written in - the dotted-only list let a bare hdr through
                   "jpeg", "bmp", "gif", "psd", "dds", "pic", "dpx",
                   "tx", "webp", "hei", "heic"}
        source = open(conversion.__file__.replace(".pyc", ".py")).read()
        tree = ast.parse(source)
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
                doc = node.body[0] if node.body else None
                if (isinstance(doc, ast.Expr)
                        and isinstance(doc.value, ast.Constant)
                        and isinstance(doc.value.value, str)):
                    docstrings.add(id(doc.value))

        named = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and id(node) not in docstrings
                    and node.value.lower().lstrip(".") in FORMATS):
                named.append((node.lineno, node.value))
        self.assertEqual(
            [], named,
            "the engine names an image format in code - which route a "
            "file needs is a measurement, and a per-format branch is "
            "how the two contracts got confused: %s" % named)

        for reader in ("splitext", "endswith", "rsplit", "rpartition",  # EVERY way of reading the name: a routing branch written with rsplit was invisible to both halves of this test, because the extension carried no dot and the call was not splitext
                       "basename"):
            self.assertNotIn(
                reader + "(", source,
                "the engine reads a file NAME with %s(); the whole "
                "point is that it reads the FILE" % reader)

    def test_iconvert_is_not_offered_where_it_cannot_help(self):
        """iconvert converts formats and has no resize option at all, so on the FIT route its full-size output is refused all over again - offering it there spends a Houdini process startup to fail."""
        fit = [name for name, _produce in conversion._FIT_ADAPTERS]
        self.assertNotIn("iconvert", fit)
        formats = [name for name, _p in conversion._FORMAT_ADAPTERS]
        self.assertIn("iconvert", formats,
                      "iconvert is the guaranteed-correct FORMAT route - "
                      "it reads every format Houdini reads, .rat included")

    def test_pillow_answers_first_on_the_format_route(self):
        """Measured on a real 117MB camera TIFF: pillow answered in 0.3s while sips and iconvert each burned their full 30s timeout ahead of it - a two-minute thumbnail per file, reported live as a hang. A pillow decline costs milliseconds (in-process, no timeout to wait out), so the formats it cannot read still reach sips and iconvert at the old speed."""
        formats = [name for name, _p in conversion._FORMAT_ADAPTERS]
        self.assertEqual("pillow", formats[0],
                         "a subprocess adapter ahead of pillow makes "
                         "every huge decodable file wait out its "
                         "timeout first")

    def test_a_foreign_format_that_is_ALSO_oversized_gets_both_halves(self):
        """The case a per-format fix cannot reach: a FORMAT converter writes a full-size temp (an 8K HDR converts to 268MB of PNG), which Qt refuses exactly like the source - the temp is then measured by the same rule and handed to the FIT route. Nothing about this is HDR-specific, which is the point."""
        if not hostos.is_macos():
            self.skipTest("sips is macOS-only")
        hdr = write_radiance_hdr(self.path("big_sky.hdr"), 1024, 512)  # decodes to 2.1MB, past the 1MB limit below - a smaller fixture converts to a temp Qt reads directly and proves nothing
        with qt_refuses(hdr, only_first=True):  # the SOURCE is genuinely foreign (Qt reads no Radiance); what is staged is the converted TEMP coming back oversized, which is what an 8K HDR does for real
            result = self.convert(hdr)
        self.assertTrue(
            result, "an oversized foreign format got nothing: %s"
                    % (result.reason,))
        self.assertFalse(uniform(result.image))
        self.assertIn(
            "->", result.via,
            "the log does not say both adapters answered, so a reader "
            "cannot tell this case from an ordinary conversion: %s"
            % (result.via,))


def _adapter_writing(colour):
    """A fake adapter that always succeeds and always writes `colour`."""
    def produce(source, out_path, ctx):
        write_png(out_path, 64, 64, flat=colour)
        return True, ""
    return produce


def _adapter_writing_a_picture():
    def produce(source, out_path, ctx):
        write_png(out_path, 64, 64)
        return True, ""
    return produce


class TheEngineVerifiesItsOwnOutput(ConversionCase):

    def setUp(self):
        super().setUp()
        self.foreign = self.path("thing.xyz")  # a file Qt cannot read, so the FORMAT order runs; its content is irrelevant - the fake adapters produce the answers
        with open(self.foreign, "wb") as fh:
            fh.write(b"not an image Qt knows")

    def test_a_converter_that_returns_a_blank_is_not_believed(self):
        """Exit 0 is not an answer to a correctness question. This is the guard, not the fix: with `-Z` back on the FORMAT route, sips would return exit 0 and a black picture, and this is what stops the tile going black anyway."""
        with mock.patch.object(conversion, "_FORMAT_ADAPTERS", (
                ("liar", _adapter_writing("#000000")),
                ("honest", _adapter_writing_a_picture()),
        )):
            result = self.convert(self.foreign)
        self.assertTrue(result, "nothing was delivered at all")
        self.assertEqual(
            "honest", result.via,
            "a solid black image was accepted from the first converter "
            "that returned exit 0")
        self.assertFalse(uniform(result.image))

    def test_the_trail_says_why_the_first_one_was_refused(self):
        with mock.patch.object(conversion, "_FORMAT_ADAPTERS", (
                ("liar", _adapter_writing("#000000")),
                ("honest", _adapter_writing_a_picture()),
        )):
            result = self.convert(self.foreign)
        refusals = dict(result.attempts)
        self.assertIn("liar", refusals)
        self.assertIn("identical", refusals["liar"])

    def test_a_genuinely_flat_image_is_still_DELIVERED(self):
        """The guard must not become its own bug: a black texture exists, and refusing to show one trades 178 black tiles for 178 missing ones - a uniform answer is a suspicion, delivered when nothing does better."""
        with mock.patch.object(conversion, "_FORMAT_ADAPTERS", (
                ("first", _adapter_writing("#000000")),
                ("second", _adapter_writing("#000000")),
        )):
            result = self.convert(self.foreign)
        self.assertTrue(
            result,
            "every converter agreed the image is flat and it was thrown "
            "away anyway - that is a missing tile for a black texture")
        self.assertTrue(
            result.uniform,
            "delivered without recording that it is one flat colour, so "
            "the log cannot tell this from a normal conversion")

    def test_a_flat_image_Qt_ITSELF_read_is_not_second_guessed(self):
        """Only converter output is judged: Qt reading a format Qt supports is the ground truth - no second decoder would do better, and two subprocesses per flat PNG in a library is a real cost for nothing."""
        flat = write_png(self.path("flat.png"), 300, 300, flat="#101010")
        calls = []

        def spy(program, args, **kw):
            calls.append(program)
            return False, "should not have been asked"

        with mock.patch.object(conversion, "_run_process", spy):
            result = self.convert(flat)
        self.assertTrue(result)
        self.assertEqual("qt", result.via)
        self.assertEqual([], calls, "a converter was run for a flat image "
                                    "Qt had already read: %s" % calls)

    def test_an_unreadable_output_is_refused_and_the_order_continues(self):
        def writes_rubbish(source, out_path, ctx):
            with open(out_path, "wb") as fh:
                fh.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
            return True, ""

        with mock.patch.object(conversion, "_FORMAT_ADAPTERS", (
                ("broken", writes_rubbish),
                ("honest", _adapter_writing_a_picture()),
        )):
            result = self.convert(self.foreign)
        self.assertEqual("honest", result.via)
        self.assertIn("unreadable", dict(result.attempts)["broken"])

    def test_a_converter_that_wrote_nothing_is_refused(self):
        def writes_nothing(source, out_path, ctx):
            return True, ""       # claims success, produced an empty file

        with mock.patch.object(conversion, "_FORMAT_ADAPTERS", (
                ("empty", writes_nothing),
                ("honest", _adapter_writing_a_picture()),
        )):
            result = self.convert(self.foreign)
        self.assertEqual("honest", result.via)


class ItAnswersWithAReasonNeverABareNone(ConversionCase):

    def test_a_cancelled_conversion_says_cancelled(self):
        """A user browsing away is not a failure, and the difference decides whether the key is retried or marked missing forever."""
        foreign = self.path("thing.xyz")
        with open(foreign, "wb") as fh:
            fh.write(b"not an image")
        result = self.convert(foreign, cancelled=lambda: True)
        self.assertFalse(result)
        self.assertEqual(conversion.REASON_CANCELLED, result.reason)

    def test_a_damaged_file_says_unreadable(self):
        broken = self.path("truncated.png")
        with open(broken, "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
        result = self.convert(broken)
        self.assertFalse(result)
        self.assertEqual(conversion.REASON_UNREADABLE, result.reason)

    def test_an_image_past_the_ceiling_says_too_large(self):
        png = write_png(self.path("enormous.png"), 1200, 1200)
        with qt_refuses(png):
            with mock.patch.object(conversion, "MAX_RESCUE_MEGABYTES", 1):
                result = self.convert(png)
        self.assertFalse(result)
        self.assertEqual(conversion.REASON_TOO_LARGE, result.reason)

    def test_the_ceiling_STOPS_the_work_rather_than_judging_it_after(self):
        """A conversion decodes the whole image before shrinking it - every route does, in-process or out - so a 32K texture is 4GB of allocation in a live Houdini: a missing thumbnail is a small thing, a lost session is not."""
        png = write_png(self.path("enormous.png"), 1200, 1200)
        called = []
        with qt_refuses(png):
            with mock.patch.object(conversion, "MAX_RESCUE_MEGABYTES", 1):
                with mock.patch.object(
                        conversion, "_run_process",
                        side_effect=lambda *a, **k: called.append(a)):
                    self.convert(png)
        self.assertEqual(
            [], called,
            "a converter still ran for an image past the ceiling - the "
            "ceiling has to stop the work, not judge it afterwards")

    def test_an_ordinary_oversized_image_is_still_converted(self):
        """Guards the ceiling: set too low, everything is declined and the test above still passes - 268MB is an 8K displacement map, an ordinary VFX texture, not an exotic case."""
        self.assertGreater(
            conversion.MAX_RESCUE_MEGABYTES, 268,
            "the shipped ceiling is below an 8K displacement map")
        png = write_png(self.path("ordinary.png"), 1200, 1200)
        with qt_refuses(png):
            result = self.convert(png)
        self.assertTrue(result, "an ordinary oversized image was declined "
                                "- the ceiling is doing more than it should")
        self.assertLessEqual(max(result.image.width(),
                                 result.image.height()), 256)


class TheSizeContract(ConversionCase):

    def test_nothing_leaves_the_engine_larger_than_asked_for(self):
        """A FORMAT converter only converts - its temp file is full-size and something has to scale it: the engine's job, in one place, for every adapter."""
        with mock.patch.object(conversion, "_FORMAT_ADAPTERS", (
                ("big", lambda src, out, ctx: (
                    write_png(out, 900, 900) and (True, "")),),
        )):
            foreign = self.path("thing.xyz")
            open(foreign, "wb").write(b"not an image")
            result = self.convert(foreign, size=128)
        self.assertTrue(result)
        self.assertLessEqual(max(result.image.width(),
                                 result.image.height()), 128)

    def test_it_keeps_the_aspect_ratio(self):
        wide = write_png(self.path("wide.png"), 400, 100)
        result = self.convert(wide, size=200)
        self.assertEqual((200, 50),
                         (result.image.width(), result.image.height()))

    def test_an_extreme_aspect_ratio_still_fits(self):
        """A 2000x2 gradient strip - a real VFX texture - scales to 128x0, which Qt reports as an EMPTY size, so the scaled read is skipped and the decoder hands back all 2000 pixels; anything past about 1:15 at 128px lands here. The case that makes the size contract load-bearing rather than decorative."""
        strip = write_png(self.path("strip.png"), 2000, 2)
        result = self.convert(strip, size=128)
        self.assertTrue(result)
        self.assertLessEqual(
            result.image.width(), 128,
            "a 2000px strip came back at full width - the size contract "
            "is not being applied where the scaled read cannot")


class TheTempFileLifetimeIsTheEngines(ConversionCase):

    def test_every_scratch_file_is_removed(self):
        """Three hand-rolled copies of this before, one per converter, each with its own mkstemp and its own finally."""
        made = []
        real = tempfile.mkstemp

        def spy(*a, **kw):
            fd, path = real(*a, **kw)
            made.append(path)
            return fd, path

        broken = self.path("truncated.png")
        with open(broken, "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
        with mock.patch.object(tempfile, "mkstemp", spy):
            self.convert(broken)

        self.assertTrue(made, "no converter ran - this test proves nothing")
        left = [p for p in made if os.path.exists(p)]
        self.assertEqual([], left, "scratch files survived the conversion: "
                                   "%s" % left)

    def test_a_failed_conversion_does_not_re_enter_the_converters(self):
        """A converter loads its own output, and a bad temp file must not loop back through the converter that produced it."""
        calls = []

        def counts(source, out_path, ctx):
            calls.append(source)
            if len(calls) > 4:  # a bound, so a genuine loop ends the test instead of recursing until the interpreter stops it
                return False, "enough"
            write_png(out_path, 400, 400)
            return True, ""

        png = write_png(self.path("big.png"), 1200, 1200)
        with qt_refuses(None):  # everything refused, temps included - the adapter's own output comes back exactly as unreadable as the source, the only condition under which a re-entry is possible
            with mock.patch.object(conversion, "_FIT_ADAPTERS",
                                   (("looper", counts),)):
                self.convert(png)
        self.assertEqual(
            1, len(calls),
            "the FIT adapter ran %d times - its own output went back "
            "through it, which is a loop" % len(calls))


class TheCancelCallbackReachesEveryConverter(ConversionCase):
    """The rescue was added after the cancel wiring and did not inherit it - without the callback, shutdown falls through to terminate(), which research.md records as orphaning the child and skipping the finally that removes the temp PNG."""

    def test_the_subprocesses_receive_it(self):
        seen = []
        with mock.patch.object(
                conversion, "_run_process",
                side_effect=lambda p, a, **kw: (
                    seen.append(kw.get("cancelled")), (False, "no"))[1]):
            foreign = self.path("thing.xyz")
            open(foreign, "wb").write(b"not an image")

            def cancelled():
                return False

            self.convert(foreign, cancelled=cancelled)
        self.assertTrue(seen, "no converter ran - this test proves nothing")
        self.assertTrue(
            all(callable(c) for c in seen),
            "a converter ran with no cancel callback, so its 100ms "
            "watchdog was never armed: %s" % seen)
        # ...and it must be THIS conversion's answer, not a stand-in.
        answers = []
        with mock.patch.object(
                conversion, "_run_process",
                side_effect=lambda p, a, **kw: (
                    answers.append(kw["cancelled"]()), (False, "no"))[1]):
            self.convert(foreign, cancelled=lambda: True)
        self.assertTrue(all(answers),
                        "the callback reaching the subprocess does not "
                        "report what the caller says: %s" % answers)

    def test_pillow_checks_it_too(self):
        """Pillow runs in process, so there is no watchdog - it polls between its two expensive steps instead."""
        source = open(conversion.__file__.replace(".pyc", ".py")).read()
        start = source.index('def _produce_pillow', 0)
        end = source.index('_SIPS_FIT =', 0)
        self.assertIn("ctx.cancelled()", source[start:end],
                      "the in-process resampler cannot be interrupted")


class OneLogLine(ConversionCase):
    """Naming who answered and why the one before it did not."""

    def events(self, *args, **kw):
        seen = []
        with mock.patch.object(conversion.debug, "event",
                               side_effect=lambda *a, **k: seen.append((a, k))):
            result = self.convert(*args, **kw)
        return result, seen

    def test_an_ordinary_image_writes_nothing(self):
        """A line per tile would flood the log rather than inform it - and a flood is what made the debug engine unreadable once."""
        png = write_png(self.path("ordinary.png"), 300, 300)
        _result, seen = self.events(png)
        self.assertEqual([], seen, "an ordinary PNG wrote to the log: %s"
                                   % seen)

    def test_a_fallback_says_who_answered_and_why_the_first_did_not(self):
        with mock.patch.object(conversion, "_FORMAT_ADAPTERS", (
                ("liar", _adapter_writing("#000000")),
                ("honest", _adapter_writing_a_picture()),
        )):
            foreign = self.path("thing.xyz")
            open(foreign, "wb").write(b"not an image")
            _result, seen = self.events(foreign)
        self.assertEqual(1, len(seen), "expected exactly one line: %s" % seen)
        data = seen[0][1]
        self.assertEqual("honest", data.get("via"))
        self.assertIn("liar", data.get("tried", ""))
        self.assertIn("identical", data.get("tried", ""))

    def test_the_line_names_the_NEED_that_was_measured(self):
        """Which of the two problems this file had is the single most useful fact in the record, and it must be the MEASURED one - reconstructed at the end from a field empty on success, every rescued oversized image was filed as a format problem, the exact class of wrong-cause log line these events exist to end."""
        png = write_png(self.path("big.png"), 1200, 1200)
        with qt_refuses(png):
            result, seen = self.events(png)
        if not result:
            self.skipTest("no out-of-process resampler on this machine")
        self.assertEqual(conversion.FIT, result.need)
        self.assertEqual(1, len(seen), "expected one line: %s" % seen)
        self.assertEqual(conversion.FIT, seen[0][1].get("need"))

        with mock.patch.object(conversion, "_FORMAT_ADAPTERS", (
                ("liar", _adapter_writing("#000000")),
                ("honest", _adapter_writing_a_picture()),
        )):
            foreign = self.path("thing.xyz")
            open(foreign, "wb").write(b"not an image")
            result, seen = self.events(foreign)
        self.assertEqual(conversion.FORMAT, result.need)
        self.assertEqual(conversion.FORMAT, seen[0][1].get("need"))

    def test_it_says_WHICH_failure_this_was_for_a_damaged_file(self):
        """A corrupt file is not a big file: every failure here used to be logged as too big for Qt, truncated downloads included - sending whoever reads the log next to measure allocation limits for a file that is simply damaged."""
        broken = self.path("truncated.png")
        with open(broken, "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
        _result, seen = self.events(broken)
        whys = " ".join(str(k.get("why", "")) for _a, k in seen)
        self.assertTrue(whys.strip(), "nothing was logged for an unreadable "
                                      "file")
        self.assertNotIn(
            "allocation limit", whys,
            "a damaged file was blamed on the allocation limit: %s" % whys)

    def test_and_says_the_allocation_limit_when_that_IS_the_cause(self):
        """The other half - without it the test above passes by never mentioning the limit at all."""
        png = write_png(self.path("huge.png"), 1200, 1200)
        with qt_refuses(png):
            with mock.patch.object(conversion, "_FIT_ADAPTERS", ()):
                _result, seen = self.events(png)
        whys = " ".join(str(k.get("why", "")) for _a, k in seen)
        self.assertIn("allocation limit", whys,
                      "an oversized file was not reported as oversized: %s"
                      % whys)

    def test_the_trail_stays_one_readable_line(self):
        """A converter's stderr can be four lines of libpng chatter."""
        def noisy(source, out_path, ctx):
            return False, "libpng error\n" * 60

        with mock.patch.object(conversion, "_FORMAT_ADAPTERS", (
                ("noisy", noisy),
                ("honest", _adapter_writing_a_picture()),
        )):
            foreign = self.path("thing.xyz")
            open(foreign, "wb").write(b"not an image")
            result = self.convert(foreign)
        why = dict(result.attempts)["noisy"]
        self.assertNotIn("\n", why)
        self.assertLessEqual(len(why), conversion._Ctx.WHY_LIMIT)


class TheEngineHasNoKnob(ConversionCase):
    """There was a Force-iconvert-only preference and a second FORMAT order to serve it: the MANUAL WORKAROUND for a converter that returned a wrong picture and reported success - exactly what this engine now catches by itself. Retired 2026-08-03. These tests pin the ABSENCE, because the tempting fix for the next misbehaving decoder is another toggle, and a knob that reorders the adapters is a second route through the engine wearing a preference's clothes; the toggle also never did what its label said - Houdini's converter cannot resize, so it left an oversized image with no route at all and no thumbnail."""

    def test_convert_image_takes_no_order_argument(self):
        import inspect

        parameters = list(inspect.signature(
            conversion.convert_image).parameters)
        self.assertEqual(
            ["path", "size", "cancelled", "hfs"], parameters,
            "the funnel grew an argument. `path`, `size` and `cancelled` "
            "describe the JOB and `hfs` is a location; anything else is a "
            "caller deciding something the engine owns: %s" % parameters)

    def test_there_is_exactly_one_order_per_need(self):
        orders = [name for name in vars(conversion)
                  if name.endswith("_ADAPTERS")]
        self.assertEqual(
            sorted(["_FIT_ADAPTERS", "_FORMAT_ADAPTERS"]), sorted(orders),
            "a second adapter order exists, which is how the engine gets "
            "two answers to one question again: %s" % orders)

    def test_the_thumbnail_engine_pushes_no_decoder_preference(self):
        import inspect

        from amaze.core import thumbnails
        parameters = list(inspect.signature(
            thumbnails.ThumbnailEngine.configure_convert).parameters)
        self.assertEqual(
            ["self", "hfs", "parallel"], parameters,
            "a decoder preference is being pushed into the engine "
            "again: %s" % parameters)

    def test_the_preference_is_gone_from_prefs_and_from_the_dialog(self):
        from amaze.prefs import prefs as prefs_mod

        self.assertFalse(
            hasattr(prefs_mod.Prefs, "texture_force_iconvert"),
            "the retired preference is back on Prefs")
        dialog = open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(
                conversion.__file__))),
            "dialogs", "prefs_dialog.py"), encoding="utf-8").read()
        self.assertNotIn(
            "ToggleSwitch(\"Force iconvert", dialog,
            "the retired control is back in Preferences")


class TheUniformCheck(ConversionCase):
    """Exact equality, never a tolerance: a near-uniform photograph of a wall is a real picture and must not be thrown away."""

    def test_a_solid_fill_is_uniform(self):
        image = QtGui.QImage(120, 120, QtGui.QImage.Format.Format_RGB32)
        image.fill(QtGui.QColor("#000000"))
        self.assertTrue(uniform(image))

    def test_a_transparent_image_is_uniform(self):
        """What sips -Z actually returned for the fixture: every pixel black AND fully transparent."""
        image = QtGui.QImage(120, 120, QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtGui.QColor(0, 0, 0, 0))
        self.assertTrue(uniform(image))

    def test_a_two_tone_image_is_not(self):
        image = QtGui.QImage(120, 120, QtGui.QImage.Format.Format_RGB32)
        image.fill(QtGui.QColor("#202020"))
        for y in range(60):
            for x in range(120):
                image.setPixelColor(x, y, QtGui.QColor("#212020"))
        self.assertFalse(uniform(image),
                         "a picture with structure was called blank")

    def test_a_faint_gradient_is_not(self):
        image = QtGui.QImage(120, 120, QtGui.QImage.Format.Format_RGB32)
        for y in range(120):
            for x in range(120):
                image.setPixelColor(x, y, QtGui.QColor(40, 40, 40 + y // 40))
        self.assertFalse(uniform(image),
                         "a low-contrast image was called blank - the check "
                         "must be exact, not a tolerance")


class TheThumbnailEngineStoppedBeingTheConverter(unittest.TestCase):
    """The Thumbnail Engine keeps its cache, its budget and its loaders - the decoder order used to live inside its worker thread, where nothing could see it and nothing checked its result."""

    def test_the_converters_machinery_is_gone_from_the_thumbnail_engine(self):
        """Read as CODE, not as prose - what must not survive is the machinery: no subprocess, no temp file, no Pillow."""
        import ast

        from amaze.core import thumbnails
        source = open(thumbnails.__file__.replace(".pyc", ".py")).read()
        tree = ast.parse(source)

        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        for module in ("tempfile", "shutil", "subprocess", "locale", "PIL"):
            self.assertNotIn(
                module, imported,
                "the Thumbnail Engine still imports %s - conversion is "
                "its own engine now" % module)

        attributes = {n.attr for n in ast.walk(tree)
                      if isinstance(n, ast.Attribute)}
        self.assertNotIn("QProcess", attributes,
                         "the Thumbnail Engine still runs subprocesses")

    def test_the_worker_asks_the_engine_and_makes_no_choices(self):
        import inspect

        from amaze.core import thumbnails
        body = inspect.getsource(thumbnails._ConvertLoader.run)
        self.assertIn("conversion.convert_image", body)
        self.assertNotIn(
            "elif", body,
            "the worker is choosing a decoder again - the order belongs "
            "to the Conversion Engine, in one place, verified")

    def test_no_extension_travels_with_a_convert_request(self):
        import inspect

        from amaze.core import thumbnails
        signature = inspect.signature(
            thumbnails.ThumbnailEngine.request_convert)
        self.assertNotIn(
            "ext", signature.parameters,
            "the caller still says which decoder family a file needs, "
            "from its NAME - that is the guess the engine replaced")


class TheWatchdogNeverSignalsOnWindows(unittest.TestCase):
    """`os.kill(pid, 0)` probes liveness on POSIX and TERMINATES on Windows, setting the exit code to the signal - so a 0 there kills the converter and reports success. ▸r/os-kill-windows"""

    def test_the_source_gates_the_signal_on_the_platform(self):
        source = inspect.getsource(conversion)
        head = source[:source.index("os.kill(pid, 0)")]
        gate = head.rindex("hostos.is_windows()")
        guard = head.rindex("if (pid")
        self.assertLess(
            guard, gate,
            "os.kill is reached without asking the platform first, so on "
            "Windows the watchdog terminates the process it is checking")

    def test_the_probe_is_reachable_on_posix(self):
        """The gate must not disable the probe everywhere - POSIX is where it does real work."""
        source = inspect.getsource(conversion)
        self.assertIn("not hostos.is_windows()", source,
                      "the gate reads as `is_windows()`, which would "
                      "disable the probe on the platform that needs it")


if __name__ == "__main__":
    unittest.main()
