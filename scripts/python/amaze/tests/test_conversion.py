"""Conversion: only FIT resamples, as `sips -Z` blacks out a Radiance .hdr; output is verified."""

import inspect
import os
import shutil
import struct
import sys
import tempfile
import threading
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import conversion  # noqa: E402
from amaze.helpers import hostos  # noqa: E402
from amaze.tests import test_support  # noqa: E402


def write_radiance_hdr(path, width=256, height=128):
    """A readable uncompressed RGBE Radiance .hdr with a gradient, so a flat failure shows."""
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
    """Make the Qt read refuse one file as oversized; `only_first` hits the first non-target file."""
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
    """A scripted killed child: dies inside the reap, or defers SIGKILL as blocked disk I/O does."""

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

    def arguments(self):
        return ["/a/stub/source.exr"]

    def moveToThread(self, thread):
        self.thread_moved_to = thread
        return True

    def deleteLater(self):
        self.deleted = True


class TheGraveyardBoundsTheStall(unittest.TestCase):
    """A child deferring SIGKILL costs half a second, not thirty: the graveyard collects it later."""

    def tearDown(self):
        conversion._ABANDONED.clear()

    def test_a_child_that_dies_in_time_is_simply_reaped(self):
        for child, killed in ((_StubProcess(reaps=True), True),
                              (_StubProcess(running=False), False)):
            with self.subTest(killed=killed):
                self.assertTrue(conversion._reap_or_abandon(child))
                self.assertEqual(killed, child.killed,
                                 "a dead child was killed, or a live one "
                                 "was left running")
                self.assertEqual([], conversion._ABANDONED)

    def test_a_sigkill_deferring_child_is_abandoned_not_awaited(self):
        child = _StubProcess(reaps=False)
        self.assertFalse(conversion._reap_or_abandon(child))
        self.assertIn(child, conversion._ABANDONED)
        self.assertTrue(child.finished.slots,
                        "nothing collects the corpse later")
        child._running = False  # released: the slot removes it from the graveyard and deletes the Qt object
        child.finished.slots[0]()
        self.assertNotIn(child, conversion._ABANDONED)
        self.assertTrue(child.deleted)

    def test_a_child_dying_during_the_handover_is_still_collected(self):
        child = _StubProcess(reaps=False)
        original_wait = child.waitForFinished  # dead before the post-connect check: finished has fired and never comes again

        def wait_then_die(ms):
            result = original_wait(ms)
            child._running = False
            return result

        child.waitForFinished = wait_then_die
        self.assertFalse(conversion._reap_or_abandon(child))
        self.assertNotIn(child, conversion._ABANDONED)
        self.assertTrue(child.deleted)


class ACompletionReapedElsewhere(unittest.TestCase):
    """Qt hears exits via SIGCHLD; a gone pid while Running means reaped elsewhere, so stop waiting."""

    @unittest.skipUnless(os.name == "posix", "SIGCHLD is POSIX-only")
    def test_a_reaped_child_returns_within_the_watchdog(self):
        import ctypes
        import signal as pysignal
        import time

        libc = ctypes.CDLL(None)
        libc.signal.restype = ctypes.c_void_p
        libc.signal.argtypes = [ctypes.c_int, ctypes.c_void_p]
        ok, err = conversion._run_process("/bin/echo", ["prime"],  # prime first: Qt installs its child-exit handler on the first QProcess start
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


def _sigkill_deferred():
    """The killed child stays Running past the grace, as uninterruptible disk I/O keeps it."""
    return mock.patch.object(conversion._Child, "waitForFinished",
                             lambda self, msecs=30000: False)


def _parked_since(before) -> list:
    return [process for process in conversion._ABANDONED if process not in before]


def _collect(parked, seconds=5.0) -> list:
    """Run the main loop until `parked` are collected; answers those left, released unawaited."""
    import time
    deadline = time.monotonic() + seconds
    while (any(p in conversion._ABANDONED for p in parked)
           and time.monotonic() < deadline):
        _app.processEvents()
        time.sleep(0.01)
    left = [p for p in parked if p in conversion._ABANDONED]
    for process in left:    # its death went unheard; marked, its destructor does not wait 30 s
        process.mark_reaped_elsewhere()
        conversion._ABANDONED.remove(process)
    return left


@unittest.skipUnless(os.name == "posix", "the stand-in children are /bin/sleep and /bin/sh")
class AChildParkedByAWorkerIsStillCollected(unittest.TestCase):
    """A worker has no event loop once run() returns; its last parked child is the main loop's."""

    def test_a_child_parked_from_a_worker_thread_is_reaped_on_the_main_loop(self):
        before = list(conversion._ABANDONED)

        class Worker(QtCore.QThread):
            def run(self):
                conversion._run_process("/bin/sleep", ["5"], timeout_ms=300)

        with _sigkill_deferred():
            worker = Worker()
            worker.start()
            self.assertTrue(worker.wait(10000), "the worker never came back")
        parked = _parked_since(before)
        self.assertEqual(1, len(parked), "premise: the killed child was not parked")
        self.assertEqual([], _collect(parked),
                         "a child parked by a finished worker is never collected")


@unittest.skipUnless(os.name == "posix", "the stand-in children are /bin/sleep and /bin/sh")
class AStuckChildEndsItsFilesChain(unittest.TestCase):
    """A child that outlives its kill is stuck in its file's reads: no second converter starts."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_stuck_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.source = os.path.join(self.dir, "cloud.exr")
        with open(self.source, "wb") as handle:
            handle.write(b"not a picture Qt can read")
        self.started = []
        before = list(conversion._ABANDONED)
        self.addCleanup(lambda: _collect(_parked_since(before)))

    def _stuck(self, source, out_path, ctx):
        self.started.append("stuck")
        return conversion._run_process("/bin/sh", ["-c", "sleep 5", source],
                                       timeout_ms=300, cancelled=ctx.cancelled)

    def _next(self, source, out_path, ctx):
        self.started.append("next")
        return False, "not reached"

    def test_an_abandoned_child_stops_its_files_chain(self):
        """When the file's own reads stall, no second converter is started on it."""
        adapters = (("stuck", self._stuck), ("next", self._next))
        with _sigkill_deferred(), mock.patch.object(conversion, "_FORMAT_ADAPTERS", adapters), \
                mock.patch.object(conversion, "_reads_promptly", lambda path: False):
            result = conversion.convert_image(self.source, 64)
        self.assertEqual(["stuck"], self.started,
                         "a second converter was started on a file whose reads are stuck")
        self.assertEqual(conversion.REASON_STALLED, result.reason)

    def test_an_abandoned_child_on_a_readable_file_lets_the_next_run(self):
        """One tool hanging is not the file hanging: a file that reads goes on to the next adapter."""
        adapters = (("stuck", self._stuck), ("next", self._next))
        with _sigkill_deferred(), mock.patch.object(conversion, "_FORMAT_ADAPTERS", adapters):
            result = conversion.convert_image(self.source, 64)
        self.assertEqual(["stuck", "next"], self.started,
                         "a converter that hung on a readable file ended its chain")
        self.assertNotEqual(conversion.REASON_STALLED, result.reason)

    def test_the_timeout_and_graveyard_records_name_the_file(self):
        adapters = (("stuck", self._stuck),)
        with test_support.captured_log() as log, _sigkill_deferred():
            with mock.patch.object(conversion, "_FORMAT_ADAPTERS", adapters):
                conversion.convert_image(self.source, 64)
        for message in ("a converter hit its timeout", "helper abandoned to the graveyard"):
            with self.subTest(message):
                found = [r for r in log.records("convert") if r.get("msg") == message]
                self.assertEqual(1, len(found), "premise: no %r record" % message)
                self.assertIn(self.source, found[0]["data"].get("args") or [],
                              "the record does not name the file")


@unittest.skipUnless(hasattr(os, "mkfifo"), "the stalled read is a FIFO with no writer")
class TheReadProbeMeasuresTheFile(unittest.TestCase):
    """The stall verdict is a bounded raw read of the file, not one converter's hang."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_probe_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def test_a_readable_file_reads(self):
        path = os.path.join(self.dir, "plain.bin")
        with open(path, "wb") as handle:
            handle.write(b"\0" * 200000)
        self.assertTrue(conversion._reads_promptly(path))

    def test_a_read_that_never_returns_is_a_stall(self):
        fifo = os.path.join(self.dir, "stuck")
        os.mkfifo(fifo)    # opening it for reading blocks until a writer comes: a real stalled read

        def _release():    # the probe's thread is still blocked; a writer opening and closing frees it
            try:
                os.close(os.open(fifo, os.O_WRONLY | os.O_NONBLOCK))
            except OSError:
                pass
        self.addCleanup(_release)
        self.assertFalse(conversion._reads_promptly(fifo, seconds=0.3))


class SipsGetsOnlyTheFormatsItReads(unittest.TestCase):
    """sips is offered a file only when its HEADER is a format sips was measured to read."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_sips_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def _file(self, name, head, tail=b""):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as handle:
            handle.write(head + b"\0" * 64 + tail)
        return path

    TGA_V1 = bytes((0, 0, 2)) + b"\0" * 9 + struct.pack("<HH", 64, 32) + bytes((24, 0))

    ALLOWED = {
        "jpeg": b"\xff\xd8\xff\xe0",
        "png": b"\x89PNG\r\n\x1a\n",
        "exr": b"\x76\x2f\x31\x01",
        "tiff-intel": b"II*\x00",
        "tiff-motorola": b"MM\x00*",
        "radiance": b"#?RADIANCE\n",
        "rgbe": b"#?RGBE\n",
        "psd": b"8BPS",
        "bmp": b"BM",
        "webp": b"RIFF\x24\x00\x00\x00WEBPVP8 ",
        "tga-1": TGA_V1,
    }

    def test_each_measured_header_is_offered_to_sips(self):
        for name, head in self.ALLOWED.items():
            with self.subTest(name):
                self.assertTrue(conversion._sips_reads(self._file(name, head)),
                                "a format sips reads was kept from it")

    def test_a_tga_is_known_by_its_footer(self):
        footer = b"\0" * 8 + b"TRUEVISION-XFILE.\0"
        path = self._file("footer.tga", b"\x00\x01\x09" + b"\0" * 15, footer)
        self.assertTrue(conversion._sips_reads(path))

    def test_a_rat_and_an_unknown_header_are_not(self):
        for name, head in (("rat", b"fbtH\x05\x00\x00\x00"), ("rat-classic", b"tarH\x80\x00"),
                           ("riff-not-webp", b"RIFF\x24\x00\x00\x00WAVE"),
                           ("unknown", b"not an image Qt knows"), ("empty", b"")):
            with self.subTest(name):
                self.assertFalse(conversion._sips_reads(self._file(name, head)),
                                 "sips was offered a file it was never measured to read")

    def _programs(self, path):
        seen = []

        def spy(program, args, **kw):
            seen.append(os.path.basename(program))
            return False, "exit 13: stand-in"

        with mock.patch.object(conversion, "_run_process", spy):
            conversion.convert_image(path, 64, hfs=os.environ.get("HFS", ""))
        return seen

    @unittest.skipUnless(hostos.is_macos(), "sips is macOS-only")
    def test_a_measured_header_reaches_sips_first(self):
        seen = self._programs(self._file("broken.png", b"\x89PNG\r\n\x1a\n"))
        self.assertTrue(seen, "premise: no converter ran")
        self.assertEqual("sips", seen[0], "sips was not the first converter: %s" % seen)

    @unittest.skipUnless(hostos.is_macos(), "sips is macOS-only")
    def test_a_rat_and_an_unknown_header_never_start_sips(self):
        for name, head in (("tex.rat", b"fbtH\x05\x00\x00\x00"), ("thing.xyz", b"not an image")):
            with self.subTest(name):
                seen = self._programs(self._file(name, head))
                self.assertNotIn("sips", seen, "sips started on a format it does not read")


def _houdini_made(hfs, tool, args):
    """A real file written by one of Houdini's own tools; None when that tool is missing."""
    import subprocess
    binary = hostos.bundled_binary(hfs, tool)
    if binary is None:
        return None
    done = subprocess.run([binary] + list(args), capture_output=True, timeout=120)
    return args[-1] if done.returncode == 0 and os.path.exists(args[-1]) else None


def _spy_programs(seen, sips_answer=None):
    """Record every converter program; `sips_answer` stands in for what sips says, else it runs."""
    real = conversion._run_process

    def spy(program, args, **kw):
        name = os.path.basename(program)
        seen.append(name)
        if name == "sips" and sips_answer is not None:
            return sips_answer
        return real(program, args, **kw)
    return mock.patch.object(conversion, "_run_process", spy)


class AHoudiniTextureGetsHoudinisConverters(unittest.TestCase):
    """A `.rat` never meets sips; a `.tx` sips refuses or hangs on still reaches iconvert."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_houdini_tex_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.hfs = os.environ.get("HFS", "")
        limit = QtGui.QImageReader.allocationLimit()
        self.addCleanup(QtGui.QImageReader.setAllocationLimit, limit)
        self.png = write_png(os.path.join(self.dir, "source.png"), 1024, 512)

    def _made(self, tool, args):
        made = _houdini_made(self.hfs, tool, args)
        if made is None:
            self.skipTest("no working $HFS/bin/%s" % tool)
        return made

    def _rat(self):
        rat = self._made("iconvert", [self.png, os.path.join(self.dir, "tex.rat")])
        with open(rat, "rb") as handle:
            self.assertEqual(b"fbtH", handle.read(4), "premise: iconvert wrote no Houdini .rat")
        return rat

    def _tx(self):    # maketx's default, a tiled TIFF: sips's header
        tx = self._made("imaketx", [self.png, os.path.join(self.dir, "tex.tx")])
        with open(tx, "rb") as handle:
            self.assertEqual(b"II*\x00", handle.read(4), "premise: not a TIFF inside")
        return tx

    def _convert(self, path, seen, pillow=True, **kw):
        adapters = tuple(a for a in conversion._FORMAT_ADAPTERS    # Pillow reads this 8-bit fixture; not a float .tx
                         if pillow or a[0] != "pillow")
        with _spy_programs(seen, **kw), mock.patch.object(conversion, "_FORMAT_ADAPTERS", adapters):
            return conversion.convert_image(path, 256, hfs=self.hfs)

    def test_a_rat_gets_a_thumbnail_without_sips(self):
        seen = []
        result = self._convert(self._rat(), seen)
        self.assertTrue(result, "a Houdini .rat got no thumbnail: %s" % (result.reason,))
        self.assertFalse(uniform(result.image))
        self.assertNotIn("sips", seen, "sips was started on a .rat")
        self.assertIn("iconvert", seen)

    def test_an_oversized_rat_is_resampled_by_houdini_not_sips(self):
        """FIT: icp scales by the declared size, so no full-size temp is written."""
        rat = self._rat()
        QtGui.QImageReader.setAllocationLimit(1)    # 1MB: 1024x512 decodes to 2.1MB, so FIT
        seen = []
        with qt_refuses(rat, declared=(1024, 512)):
            result = self._convert(rat, seen)
        self.assertTrue(result, "an oversized .rat got no thumbnail: %s" % (result.attempts,))
        self.assertNotIn("sips", seen, "sips was started on a .rat")
        self.assertEqual("icp (resampling)", result.via)
        self.assertEqual((256, 128), (result.image.width(), result.image.height()))

    @unittest.skipUnless(hostos.is_macos(), "sips is macOS-only")
    def test_a_tx_sips_refuses_reaches_iconvert(self):
        seen = []
        result = self._convert(self._tx(), seen, pillow=False,
                               sips_answer=(False, "exit 13: Error 13"))
        self.assertEqual("sips", seen[0], "a .tx's header is measured to go to sips first: %s" % seen)
        self.assertTrue(result, "a .tx sips refused got no thumbnail: %s" % (result.attempts,))
        self.assertEqual("iconvert", result.via)

    @unittest.skipUnless(hostos.is_macos(), "sips is macOS-only")
    def test_a_tx_whose_sips_hangs_on_a_readable_file_reaches_iconvert(self):
        seen = []
        result = self._convert(self._tx(), seen, pillow=False,
                               sips_answer=(False, conversion.ABANDONED))
        self.assertEqual("sips", seen[0])
        self.assertTrue(result, "a sips hang ended the chain on a file that reads: %s"
                        % (result.attempts,))
        self.assertEqual("iconvert", result.via)

def _exr_header(width, height) -> bytes:
    """An OpenEXR header laid out as Houdini's iconvert writes one, with a box2i data window."""
    def attribute(name, kind, value):
        return name + b"\0" + kind + b"\0" + struct.pack("<i", len(value)) + value
    window = struct.pack("<4i", 0, 0, width - 1, height - 1)
    return (b"\x76\x2f\x31\x01" + struct.pack("<I", 2)
            + attribute(b"compression", b"compression", b"\x03")
            + attribute(b"dataWindow", b"box2i", window)
            + attribute(b"displayWindow", b"box2i", window)
            + b"\0" + b"\0" * 64)    # the header's end, then where offsets and pixels would be


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
        """The outcome: a Radiance .hdr keeps its picture, held up by both the split and the guard."""
        if not hostos.is_macos():
            self.skipTest("sips is macOS-only; the FORMAT route here is "
                          "iconvert, which never had this failure")
        hdr = write_radiance_hdr(self.path("sky.hdr"), 1024, 512)  # bigger than asked for: -Z 256 on a source within 256px is a no-op
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
        """The split, read off the command line: the FORMAT route never passes `-Z`; Qt scales it."""
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
        """The FIT route passes `-Z`, or Qt refuses the full-size temp all over again."""
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

    def test_iconvert_is_not_offered_where_it_cannot_help(self):
        """iconvert has no resize option, so it is never offered on the FIT route."""
        fit = [name for name, _produce in conversion._FIT_ADAPTERS]
        self.assertNotIn("iconvert", fit)
        formats = [name for name, _p in conversion._FORMAT_ADAPTERS]
        self.assertIn("iconvert", formats,
                      "iconvert is the guaranteed-correct FORMAT route - "
                      "it reads every format Houdini reads, .rat included")
        self.assertEqual("pillow", formats[0],
                         "a subprocess adapter ahead of pillow makes "
                         "every huge decodable file wait out its "
                         "timeout first")

    def test_a_foreign_format_that_is_ALSO_oversized_gets_both_halves(self):
        """A FORMAT temp too big for Qt is measured by the same rule and handed to the FIT route."""
        if not hostos.is_macos():
            self.skipTest("sips is macOS-only")
        hdr = write_radiance_hdr(self.path("big_sky.hdr"), 1024, 512)  # decodes to 2.1MB, past the 1MB limit below
        with qt_refuses(hdr, only_first=True):  # Qt reads no Radiance; only the converted temp is staged as oversized
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
        self.foreign = self.path("thing.xyz")  # a file Qt cannot read, so the FORMAT order runs; fake adapters answer
        with open(self.foreign, "wb") as fh:
            fh.write(b"not an image Qt knows")

    def test_a_converter_that_returns_a_blank_is_not_believed(self):
        """The guard: exit 0 with a blank picture is not believed."""
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
        refusals = dict(result.attempts)
        self.assertIn("liar", refusals, "the trail does not say why the "
                      "first converter was refused")
        self.assertIn("identical", refusals["liar"])

    def test_a_genuinely_flat_image_is_still_DELIVERED(self):
        """A uniform answer is a suspicion, still delivered when nothing does better: black exists."""
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
        """Only converter output is judged: a Qt read of a format Qt supports is ground truth."""
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

        def writes_nothing(source, out_path, ctx):
            return True, ""       # claims success, produced an empty file

        for bad in (writes_rubbish, writes_nothing):
            with self.subTest(adapter=bad.__name__), mock.patch.object(
                    conversion, "_FORMAT_ADAPTERS", (
                        ("broken", bad),
                        ("honest", _adapter_writing_a_picture()))):
                result = self.convert(self.foreign)
                self.assertEqual("honest", result.via)
                self.assertIn("unreadable", dict(result.attempts)["broken"])


class ItAnswersWithAReasonNeverABareNone(ConversionCase):

    def test_a_cancelled_conversion_says_cancelled(self):
        """Browsing away is not a failure: it decides whether the key is retried or marked missing."""
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
        called = []
        with qt_refuses(png):
            with mock.patch.object(conversion, "MAX_RESCUE_MEGABYTES", 1):
                with mock.patch.object(
                        conversion, "_run_process",
                        side_effect=lambda *a, **k: called.append(a)):
                    result = self.convert(png)
        self.assertFalse(result)
        self.assertEqual(conversion.REASON_TOO_LARGE, result.reason)
        self.assertEqual(
            [], called,
            "a converter still ran for an image past the ceiling - a 32K "
            "texture is 4GB of allocation in a live Houdini")

    def test_an_ordinary_oversized_image_is_still_converted(self):
        """Guards the ceiling from below: 268MB is an 8K displacement map, an ordinary texture."""
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


class AnEXRIsMeasuredFromItsOwnHeader(ConversionCase):
    """Qt declares no size for an EXR, so the decoded ceiling reads its header's data window."""

    def _converters_started(self, width, height):
        path = self.path("plate.exr")
        with open(path, "wb") as handle:
            handle.write(_exr_header(width, height))
        _image, declared, _error = conversion._read_qt(path, 64)
        self.assertFalse(declared.isValid(), "premise: Qt itself declared the EXR's size")
        started = []

        def converter(source, out_path, ctx):
            started.append(source)
            return False, "no answer"

        with mock.patch.object(conversion, "_FORMAT_ADAPTERS", (("converter", converter),)):
            result = self.convert(path, 64)
        return started, result

    def test_an_exr_past_the_ceiling_is_declined_before_any_converter(self):
        started, result = self._converters_started(20000, 16000)    # 1,280 MB decoded
        self.assertEqual([], started, "a converter was started on an EXR past the ceiling")
        self.assertEqual(conversion.REASON_TOO_LARGE, result.reason)

    def test_an_ordinary_exr_still_reaches_the_converters(self):
        started, result = self._converters_started(4096, 2048)
        self.assertEqual(1, len(started), "an EXR within the ceiling was refused")
        self.assertEqual(conversion.REASON_UNREADABLE, result.reason)


class TheSizeContract(ConversionCase):

    def test_nothing_leaves_the_engine_larger_than_asked_for(self):
        """A FORMAT temp is full-size; the engine scales it, in one place, for every adapter."""
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
        """A 2000x2 strip scales to 128x0, an empty size to Qt, so the scaled read is skipped."""
        strip = write_png(self.path("strip.png"), 2000, 2)
        result = self.convert(strip, size=128)
        self.assertTrue(result)
        self.assertLessEqual(
            result.image.width(), 128,
            "a 2000px strip came back at full width - the size contract "
            "is not being applied where the scaled read cannot")


class TheTempFileLifetimeIsTheEngines(ConversionCase):

    def test_every_scratch_file_is_removed(self):
        """The engine owns every scratch file, for every converter."""
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
        """A bad temp file never loops back through the converter that produced it."""
        calls = []

        def counts(source, out_path, ctx):
            calls.append(source)
            if len(calls) > 4:  # a bound, so a genuine loop ends the test
                return False, "enough"
            write_png(out_path, 400, 400)
            return True, ""

        png = write_png(self.path("big.png"), 1200, 1200)
        with qt_refuses(None):  # everything refused, temps included: the only way a re-entry is possible
            with mock.patch.object(conversion, "_FIT_ADAPTERS",
                                   (("looper", counts),)):
                self.convert(png)
        self.assertEqual(
            1, len(calls),
            "the FIT adapter ran %d times - its own output went back "
            "through it, which is a loop" % len(calls))


class TheCancelCallbackReachesEveryConverter(ConversionCase):
    """Without the callback, terminate() orphans the child and skips the temp cleanup."""

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
        # and it must be this conversion answer, not a stand-in
        answers = []
        with mock.patch.object(
                conversion, "_run_process",
                side_effect=lambda p, a, **kw: (
                    answers.append(kw["cancelled"]()), (False, "no"))[1]):
            self.convert(foreign, cancelled=lambda: True)
        self.assertTrue(all(answers),
                        "the callback reaching the subprocess does not "
                        "report what the caller says: %s" % answers)


class TwoPillowConversionsLeaveTheBombGuardAlone(ConversionCase):
    """Pillow's `MAX_IMAGE_PIXELS` is process-global and up to eight converter threads lift it."""

    def _convert_in(self, name, source):
        out = self.path(name + ".png")
        ctx = conversion._Ctx(source, 64, None, self.hfs)
        thread = threading.Thread(
            target=conversion._produce_pillow, args=(source, out, ctx),
            name=name)
        thread.start()
        return thread

    def test_overlapping_conversions_restore_the_starting_value(self):
        if not conversion._have_pillow():
            self.skipTest("no Pillow in this Houdini's Python")
        from PIL import Image
        starting = Image.MAX_IMAGE_PIXELS
        self.addCleanup(setattr, Image, "MAX_IMAGE_PIXELS", starting)
        source = write_png(self.path("ramp.png"), 96, 96)
        real_open = Image.open
        inside = {"first": threading.Event(), "second": threading.Event()}
        go = {"first": threading.Event(), "second": threading.Event()}

        def held_open(*args, **kwargs):
            name = threading.current_thread().name
            inside[name].set()
            go[name].wait(5)
            return real_open(*args, **kwargs)

        with mock.patch.object(Image, "open", held_open):
            first = self._convert_in("first", source)
            self.assertTrue(inside["first"].wait(5), "premise: no open ran")
            second = self._convert_in("second", source)
            inside["second"].wait(0.5)    # inside the lift unless a lock holds it out
            go["first"].set()
            first.join(10)
            go["second"].set()
            second.join(10)
        self.assertEqual(
            starting, Image.MAX_IMAGE_PIXELS,
            "two overlapping conversions left Pillow's decompression-bomb "
            "guard at %r for the rest of the session"
            % (Image.MAX_IMAGE_PIXELS,))


class OneLogLine(ConversionCase):
    """Naming who answered and why the one before it did not."""

    def events(self, *args, **kw):
        seen = []
        with mock.patch.object(conversion.debug, "event",
                               side_effect=lambda *a, **k: seen.append((a, k))):
            result = self.convert(*args, **kw)
        return result, seen

    def test_an_ordinary_image_writes_nothing(self):
        """A line per tile would flood the log rather than inform it."""
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
        """The line names the measured need, format or size, never one reconstructed afterwards."""
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
        """A corrupt file is not a big file: the log says damaged, not too big for Qt."""
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
        """The other half: when the limit is the cause, the line says so."""
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


class TheUniformCheck(ConversionCase):
    """Exact equality, never a tolerance: a near-uniform photograph of a wall is a real picture."""

    def test_only_an_exactly_flat_image_is_uniform(self):
        solid = QtGui.QImage(120, 120, QtGui.QImage.Format.Format_RGB32)
        solid.fill(QtGui.QColor("#000000"))
        clear = QtGui.QImage(120, 120, QtGui.QImage.Format.Format_ARGB32)
        clear.fill(QtGui.QColor(0, 0, 0, 0))    # what sips -Z returned: black AND transparent
        faint = QtGui.QImage(120, 120, QtGui.QImage.Format.Format_RGB32)
        for y in range(120):
            for x in range(120):
                faint.setPixelColor(x, y, QtGui.QColor(40, 40, 40 + y // 40))
        for label, image, flat in (("solid", solid, True),
                                   ("transparent", clear, True),
                                   ("faint gradient", faint, False)):
            with self.subTest(image=label):
                self.assertEqual(
                    flat, uniform(image),
                    "the check must be exact, not a tolerance: a "
                    "low-contrast picture is not blank")


class TheWatchdogNeverSignalsOnWindows(unittest.TestCase):
    """`os.kill(pid, 0)` probes liveness on POSIX but terminates on Windows ▸r/os-kill-windows"""

    def test_the_source_gates_the_signal_on_the_platform(self):
        source = inspect.getsource(conversion)
        head = source[:source.index("os.kill(pid, 0)")]
        gate = head.rindex("hostos.is_windows()")
        guard = head.rindex("if (pid")
        self.assertLess(
            guard, gate,
            "os.kill is reached without asking the platform first, so on "
            "Windows the watchdog terminates the process it is checking")


if __name__ == "__main__":
    unittest.main()
