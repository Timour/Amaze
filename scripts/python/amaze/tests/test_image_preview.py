"""The picture reader: which files it reads, at what width, and what its Reader keeps and drops."""

import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtGui, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401
import numpy  # noqa: E402
import OpenImageIO as oiio  # noqa: E402

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import file_info, image_preview  # noqa: E402
from amaze.tests import test_support  # noqa: E402


def _write(path, width, height, channels=3, kind=oiio.UINT8, value=0.5, names=None, mips=False):
    """A flat picture of `value`; with `mips` a tiled file carrying every smaller level."""
    spec = oiio.ImageSpec(width, height, channels, kind)
    if names:
        spec.channelnames = names
    picture = oiio.ImageBuf(spec)
    picture.set_pixels(oiio.ROI(0, width, 0, height),
                       numpy.full((height, width, channels), value, dtype=numpy.float32))
    if mips:
        if not oiio.ImageBufAlgo.make_texture(oiio.MakeTxTexture, picture, path):
            raise AssertionError(oiio.geterror())
    elif not picture.write(path):
        raise AssertionError(picture.geterror())


class _Files(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="amaze_preview_")
        self.addCleanup(shutil.rmtree, self.folder, True)

    def file(self, name, *args, **kwargs):
        path = os.path.join(self.folder, name)
        _write(path, *args, **kwargs)
        return path


class WhichFilesItReads(unittest.TestCase):

    def test_by_ending_and_never_rat_or_pic(self):
        for name in ("a.exr", "a.hdr", "a.jpg", "a.jpeg", "a.png", "a.bmp", "a.gif", "a.tif", "a.tiff",
                     "a.tga", "a.tx", "A.EXR"):
            with self.subTest(name=name):
                self.assertTrue(image_preview.can_read("/lib/" + name))
        for name in ("a.rat", "a.pic", "a.psd", "a.bgeo.sc", "a.usd", "a", "exr"):
            with self.subTest(name=name):
                self.assertFalse(image_preview.can_read("/lib/" + name))

    def test_every_ending_is_one_the_info_pane_calls_an_image(self):
        self.assertEqual(set(), set(image_preview.ENDINGS) - set(file_info.IMAGE_ENDINGS))


class AFileBecomesAnImage(_Files):

    def test_each_format_is_read_and_scaled_to_the_width(self):
        for name, kind in (("a.exr", oiio.HALF), ("a.hdr", oiio.FLOAT), ("a.tif", oiio.UINT16),
                           ("a.tga", oiio.UINT8), ("a.jpg", oiio.UINT8), ("a.png", oiio.UINT8),
                           ("a.bmp", oiio.UINT8)):
            with self.subTest(name=name):
                image = image_preview.read(self.file(name, 400, 200, kind=kind), 100)
                self.assertIsNotNone(image)
                self.assertEqual((100, 50), (image.width(), image.height()))

    def test_a_photo_stored_turned_is_as_wide_as_asked_once_it_is_upright(self):
        path = os.path.join(self.folder, "turned.jpg")
        spec = oiio.ImageSpec(400, 200, 3, oiio.UINT8)
        spec.attribute("Orientation", 6)    # stored lying down, shown turned a quarter: a camera's flag
        stored = oiio.ImageBuf(spec)
        oiio.ImageBufAlgo.fill(stored, (0.4, 0.5, 0.6))
        self.assertTrue(stored.write(path), stored.geterror())
        turned = QtGui.QImageReader(path).transformation()
        self.assertEqual(QtGui.QImageIOHandler.Transformation.TransformationRotate90, turned)
        image = image_preview.read(path, 100)
        self.assertEqual((100, 200), (image.width(), image.height()))

    def test_a_scaled_picture_keeps_only_the_channels_it_shows(self):
        for channels, names, form in (
                (2, ("Y", "A"), QtGui.QImage.Format.Format_Grayscale8),
                (4, ("R", "G", "B", "Z"), QtGui.QImage.Format.Format_RGB888)):
            with self.subTest(channels=channels):
                path = self.file("c%d.exr" % channels, 200, 100, channels, oiio.HALF, names=names)
                image = image_preview.read(path, 100)
                self.assertEqual((100, 50, form), (image.width(), image.height(), image.format()))

    def test_a_picture_narrower_than_the_width_keeps_its_size(self):
        for name in ("a.exr", "a.png"):
            with self.subTest(name=name):
                image = image_preview.read(self.file(name, 40, 20), 100)
                self.assertEqual((40, 20), (image.width(), image.height()))

    def test_scene_values_get_the_view_transform_and_display_values_do_not(self):
        linear = image_preview.read(self.file("a.exr", 8, 8, kind=oiio.HALF, value=0.18), 8)
        shown = image_preview.read(self.file("a.tif", 8, 8, kind=oiio.UINT8, value=0.18), 8)
        self.assertAlmostEqual(46, shown.pixelColor(4, 4).red(), delta=1)    # 0.18 of 255, untouched
        self.assertGreater(linear.pixelColor(4, 4).red(), 80,    # mid grey through a display view is far above 46
                           "0.18 in an EXR was shown as if it were a display value")

    def test_a_render_with_passes_shows_its_colour_and_alpha_only(self):
        for names, form in ((["R", "G", "B", "A"], QtGui.QImage.Format.Format_RGBA8888_Premultiplied),
                            (["R", "G", "B", "Z"], QtGui.QImage.Format.Format_RGB888)):
            names = names + ["pass%d" % n for n in range(6)]
            path = self.file("a%s.exr" % names[3], 16, 16, channels=10, kind=oiio.HALF, names=names)
            self.assertGreater(10, image_preview.MANY_CHANNELS + 1)
            image = image_preview.read(path, 8)
            with self.subTest(fourth=names[3]):
                self.assertEqual((8, 8, form), (image.width(), image.height(), image.format()))

    def test_alpha_is_kept_so_a_cutout_shows_what_is_behind_it(self):
        for name, kind in (("a.exr", oiio.HALF), ("a.tif", oiio.UINT8), ("a.png", oiio.UINT8)):
            path = os.path.join(self.folder, name)
            spec = oiio.ImageSpec(8, 8, 4, kind)
            picture = oiio.ImageBuf(spec)
            pixels = numpy.zeros((8, 8, 4), dtype=numpy.float32)
            pixels[:, 4:] = (0.18, 0.18, 0.18, 1.0)    # the right half solid, the left half empty
            picture.set_pixels(oiio.ROI(0, 8, 0, 8), pixels)
            self.assertTrue(picture.write(path))
            image = image_preview.read(path, 8)
            with self.subTest(name=name):
                self.assertTrue(image.hasAlphaChannel())
                self.assertEqual((0, 255), (image.pixelColor(1, 4).alpha(), image.pixelColor(6, 4).alpha()))

    def test_a_single_channel_is_shown_as_grey(self):
        image = image_preview.read(self.file("a.exr", 16, 16, channels=1, kind=oiio.HALF, names=["Y"]), 8)
        self.assertEqual(QtGui.QImage.Format.Format_Grayscale8, image.format())

    def test_the_smallest_level_wide_enough_is_the_one_read(self):
        path = self.file("a.tx", 512, 512, kind=oiio.UINT8, mips=True)
        seen = []
        real = oiio.ImageBuf

        def spy(*args):
            seen.append(args)
            return real(*args)

        oiio.ImageBuf = spy
        self.addCleanup(setattr, oiio, "ImageBuf", real)
        image = image_preview.read(path, 100)
        self.assertEqual((100, 100), (image.width(), image.height()))
        self.assertIn((path, 0, 2), seen, "512, 256, 128: level 2 is the smallest at least 100 wide")

    def test_a_file_that_is_not_a_picture_and_a_missing_one_are_none(self):
        path = os.path.join(self.folder, "a.exr")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("not a picture")
        self.assertIsNone(image_preview.read(path, 100))
        self.assertIsNone(image_preview.read(os.path.join(self.folder, "gone.png"), 100))

    def test_a_cancelled_read_is_none(self):
        self.assertIsNone(image_preview.read(self.file("a.exr", 64, 64), 32, lambda: True))

    def test_nothing_is_written_beside_the_file(self):
        path = self.file("a.exr", 64, 64, kind=oiio.HALF)
        image_preview.read(path, 32)
        self.assertEqual(["a.exr"], os.listdir(self.folder))


class TheReader(_Files):

    def setUp(self):
        super().setUp()
        self.reader = image_preview.Reader()
        self.addCleanup(self.reader.deleteLater)
        self.addCleanup(self.reader.stop)
        self.got = []
        self.reader.ready.connect(lambda path, image: self.got.append((path, image)))

    def _wait(self, count=1):
        self.assertTrue(test_support.pump_until(lambda: len(self.got) >= count), "no picture arrived")

    def test_a_read_arrives_and_the_same_ask_then_answers_at_once(self):
        path = self.file("a.exr", 400, 200, kind=oiio.HALF)
        self.reader.ask(path, 100)
        self._wait()
        self.assertEqual((path, 100), (self.got[0][0], self.got[0][1].width()))
        self.assertEqual("", self.got[0][1].text(image_preview.WHOLE))

    def test_an_image_narrower_than_asked_is_marked_as_the_whole_file(self):
        path = self.file("a.exr", 400, 200, kind=oiio.HALF)
        self.reader.ask(path, 900)
        self._wait()
        self.assertEqual((400, "1"), (self.got[0][1].width(), self.got[0][1].text(image_preview.WHOLE)))

    def test_it_keeps_no_picture_so_a_changed_file_shows_changed(self):
        path = self.file("a.png", 40, 20)
        self.reader.ask(path, 100)
        self._wait()
        _write(path, 60, 20)
        self.reader.ask(path, 100)
        self._wait(2)
        self.assertEqual(60, self.got[1][1].width())
        self.assertFalse(hasattr(self.reader, "_kept"))

    def test_the_newer_ask_wins_and_stop_silences_the_read(self):
        first, second = self.file("a.exr", 64, 64), self.file("b.exr", 64, 64)
        self.reader.ask(first, 32)
        self.reader.ask(second, 32)
        self._wait()
        test_support.pump_until(lambda: False, 0.2)
        self.assertEqual([second], [path for path, _image in self.got])
        self.reader.ask(first, 32)
        self.reader.stop()
        test_support.pump_until(lambda: False, 0.2)
        self.assertEqual(1, len(self.got))

    def test_a_file_that_cannot_be_read_answers_none_and_a_missing_one_asks_nothing(self):
        path = os.path.join(self.folder, "a.exr")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("not a picture")
        self.reader.ask(path, 100)
        self._wait()
        self.assertEqual([(path, None)], self.got)
        gone = os.path.join(self.folder, "gone.exr")
        self.reader.ask(gone, 100)
        self._wait(2)
        self.assertEqual((gone, None), self.got[1])


if __name__ == "__main__":
    unittest.main()
