"""File picture conversion: one test per requirement in docs/requirements/picture-conversion.md."""

import os
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from amaze.core import conversion, thumbnails, workers  # noqa: E402
from amaze.tests import test_support  # noqa: E402

SLEEPER = [test_support.plain_python(), "-c", "import time; time.sleep(30)"]
REFUSER = [test_support.plain_python(), "-c", "raise SystemExit(3)"]


def picture(path: str, width: int = 64, height: int = 64, flat: str = "") -> str:
    """A PNG of one colour when `flat`, else a pattern; its path."""
    image = QtGui.QImage(width, height, QtGui.QImage.Format.Format_RGB32)
    image.fill(QtGui.QColor(flat or "#204060"))
    for x in range(0 if flat else width):
        image.setPixelColor(x, (x * 7) % height, QtGui.QColor("#f0c020"))
    assert image.save(path, "PNG"), "premise: the picture was not written"
    return path


def exr_header(width: int, height: int) -> bytes:
    """An OpenEXR header with a box2i data window: Qt declares no size for it, the header does."""
    window = struct.pack("<4i", 0, 0, width - 1, height - 1)
    return (b"\x76\x2f\x31\x01" + struct.pack("<I", 2) + b"dataWindow\0box2i\0"
            + struct.pack("<i", len(window)) + window + b"\0" * 65)


def snapshot(folder: str) -> dict:
    """Each file in `folder`: when it last changed, and its bytes."""
    found = {}
    for name in sorted(os.listdir(folder)):
        with open(os.path.join(folder, name), "rb") as handle:
            found[name] = (os.stat(os.path.join(folder, name)).st_mtime_ns, handle.read())
    return found


def writing(width: int = 64, height: int = 64, flat: str = ""):
    """A converter that writes a picture to its output."""
    return lambda source, out, ctx: (picture(out, width, height, flat), (True, ""))[1]


def running(command):
    """A converter that runs `command` as its process, as sips, icp and iconvert are run."""
    return lambda source, out, ctx: conversion._run_process(
        command[0], command[1:], cancelled=ctx.cancelled)


def converters(*adapters):
    """`adapters` as the FORMAT route's converters, named by their place."""
    return mock.patch.object(conversion, "_FORMAT_ADAPTERS",
                             tuple(("converter %d" % n, a) for n, a in enumerate(adapters)))


class Undying:
    """A converter stuck in a read of the file: a kill does nothing, every wait times out."""

    args = ["stuck converter"]

    def kill(self):
        pass

    def wait(self, timeout=None):
        time.sleep(timeout or 0)
        raise subprocess.TimeoutExpired(self.args, timeout)

    def poll(self):
        return None


class ConversionTest(unittest.TestCase):
    """The user's files in a folder of their own, and conversion's temp folder apart."""

    def setUp(self):
        self.dir = test_support.scratch_dir("amaze_conversion_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.temp, self.user = os.path.join(self.dir, "temp"), os.path.join(self.dir, "user")
        os.makedirs(self.temp)
        os.makedirs(self.user)
        for patcher in (mock.patch.object(tempfile, "tempdir", self.temp),
                        mock.patch.object(conversion, "_ABANDONED", [])):
            patcher.start()
            self.addCleanup(patcher.stop)

    def user_file(self, name: str, data: bytes = b"no picture Qt can read") -> str:
        with open(os.path.join(self.user, name), "wb") as handle:
            handle.write(data)
        return os.path.join(self.user, name)

    def test_cv01_converting_only_reads_the_users_file(self):
        works = picture(os.path.join(self.user, "works.png"))
        converted, fails, cancelled = (self.user_file(name) for name in ("a.rat", "b.rat", "c.rat"))
        before, stop = snapshot(self.user), time.monotonic() + 0.3
        for path, adapter, answer in ((works, writing(), True), (converted, writing(), True),
                                      (fails, running(REFUSER), False),
                                      (cancelled, running(SLEEPER), False)):
            with self.subTest(os.path.basename(path)), converters(adapter):
                result = conversion.convert_image(
                    path, 64, cancelled=lambda: path == cancelled and time.monotonic() > stop)
                self.assertEqual(answer, bool(result), result.attempts)
        self.assertEqual(before, snapshot(self.user), "a file beside the user's was changed")
        self.assertEqual([], os.listdir(self.temp), "a temporary file was left")

    def test_cv10_converting_never_crashes_or_holds_up_houdini(self):
        asked = []
        ask = lambda *a: asked.append(a) or (False, "asked")    # noqa: E731
        declared = mock.patch.object(conversion, "_read_qt", lambda path, size: (
            None, QtCore.QSize(20000, 16000), ""))    # 1,280 MB decoded
        fit = mock.patch.object(conversion, "_FIT_ADAPTERS", (("fit", ask),))
        huge = self.user_file("huge.exr", exr_header(20000, 16000))
        for path, route in ((huge, mock.MagicMock()), (self.user_file("huge.tif"), declared)):
            with route, converters(ask), fit:
                self.assertEqual(conversion.REASON_TOO_LARGE,
                                 conversion.convert_image(path, 64).reason)
        self.assertEqual([], asked, "a picture over 1 GB decoded reached a converter")

        source, real_spawn = self.user_file("slow.rat"), conversion._spawn
        for cancel, why in ((False, conversion.TIMED_OUT), (True, conversion.CANCELLED)):
            children = []
            with self.subTest(why), converters(running(SLEEPER)), mock.patch.object(
                    conversion, "CONVERT_TIMEOUT_MS", 300), mock.patch.object(
                    conversion, "_spawn",
                    lambda *a: children.append(real_spawn(*a)) or children[-1]):
                started = time.monotonic()
                result = conversion.convert_image(source, 64, cancelled=lambda: cancel and children)
            self.assertIn(("converter 0", why), result.attempts)
            self.assertLess(time.monotonic() - started, 5.0, "the converter was not stopped")
            self.assertIsNotNone(children[0].poll(), "the converter outlived its stop")

        ran, spawned = [], threading.Event()
        with mock.patch.object(conversion, "_spawn", lambda *a: spawned.set() or Undying()), \
                converters(running(SLEEPER), lambda *a: ran.append(a) or (False, "")):
            with mock.patch.object(conversion, "CONVERT_TIMEOUT_MS", 300), \
                    mock.patch.object(conversion, "_reads_promptly", lambda path: False):
                self.assertEqual(conversion.REASON_STALLED,
                                 conversion.convert_image(source, 64).reason)
            self.assertEqual([], ran, "a file whose reads hang got a second converter")
            spawned.clear()
            engine = thumbnails.ThumbnailEngine()
            loader = thumbnails._ConvertLoader([("key", source, 64, "", 0)], None)
            engine._threads.append(loader)
            loader.start()
            self.assertTrue(spawned.wait(10), "premise: the worker never started its converter")
            started = time.monotonic()
            engine.shutdown()
            waited = time.monotonic() - started
        self.assertLess(waited, 1.5, "Houdini waited %.1f s on a stuck converter" % waited)
        self.assertTrue(loader.isFinished() and loader not in workers._unstoppable,
                        "the worker was not free when Houdini stopped waiting")

    def test_cv20_a_picture_is_no_larger_than_asked_in_its_own_shape(self):
        wide = picture(os.path.join(self.user, "wide.png"), 400, 100)
        self.assertEqual(QtCore.QSize(128, 32), conversion.convert_image(wide, 128).image.size())
        strip = picture(os.path.join(self.user, "strip.png"), 2000, 2)    # scaled after it is read
        self.assertLessEqual(conversion.convert_image(strip, 128).image.width(), 128)
        with converters(writing(900, 300)):
            image = conversion.convert_image(self.user_file("wide.rat"), 128).image
        self.assertEqual(128, image.width())
        self.assertAlmostEqual(3.0, image.width() / image.height(), delta=0.1)

    def test_cv21_a_blank_output_is_no_picture_unless_the_file_is_one_colour(self):
        source = self.user_file("blank.rat")
        with converters(writing(flat="#000000"), writing()):
            self.assertEqual("converter 1", conversion.convert_image(source, 64).via,
                             "a converter's blank output was taken as the picture")
        with converters(writing(flat="#000000"), writing(flat="#000000")):
            result = conversion.convert_image(source, 64)
        self.assertTrue(result.uniform and result.image is not None,
                        "a file of one colour got no picture")

    def test_cv22_a_conversion_that_did_not_finish_is_no_verdict(self):
        engine, source = thumbnails.ThumbnailEngine(), self.user_file("tex.rat")
        absent = [os.path.join(self.dir, "no-such-converter")]
        for key, command, cancel in (("timed out", SLEEPER, False), ("cancelled", SLEEPER, True),
                                     ("did not start", absent, False), ("refused", REFUSER, False)):
            with self.subTest(key), converters(running(command)), mock.patch.object(
                    conversion, "CONVERT_TIMEOUT_MS", 300):
                loader = thumbnails._ConvertLoader([(key, source, 64, "", 0)], None)
                loader.unfinished.connect(engine._on_unfinished)
                engine._states[key] = "pending"
                with mock.patch.object(loader, "_cancelled", lambda: cancel):
                    loader.run()
                self.assertEqual(key != "refused", engine.unfinished(key))


if __name__ == "__main__":
    unittest.main()
