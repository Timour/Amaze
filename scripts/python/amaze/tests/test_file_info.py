"""The info pane's file facts: the parsers of Houdini's tools, the runner, `read` and `Reader`."""

import gc
import os
import shutil
import stat
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(   # three dirnames up is scripts/python: the dev tree, not the install
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # before the app exists ▸p/first-app-picks-the-platform
from PySide6 import QtCore, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402
from amaze.core import file_info  # noqa: E402
from amaze.helpers import hostos  # noqa: E402
from amaze.tests import test_support  # noqa: E402 - redirects the debug log

EXR_TEXT = """File:           /path/amplitudes.exr (oiio format)
Resolution:     64 x 64
Data Window:    (0,0)-(63,63)
Data:           16 bit float
Color Model:    RGBA
Color Space:    linear
Channel Depth:  16 x 4 (64 bpp)
Format Specific Information:
    Image Type:          Flat
    Compression:         ZIP, Multi-scanline blocks (zip)
    Storage:             Scanline
    Created:             2024:04:25 10:59:10
    MipMaps:             true
"""

RAT_TEXT = """File:           /path/Mandril.rat (RAT format)
Resolution:     256 x 256
Data:           8 bit integer
Color Model:    RGBA
Color Space:    srgb
Channel Depth:  8 x 4 (32 bpp)
Format Specific Information:
    TBF v2.0 File Type: 2D Raster
    MIP Resolutions: 256x256, 128x128, 64x64, 32x32, 16x16, 8x8, 4x4, 2x2, 1x1
      Saved Options:
      C::constantalpha     := 1
"""

PIC_TEXT = """File:             Mandril.pic (Houdini format)
Resolution:       256 x 256

C (r,g,b):
  Data:           8 bit integer
  Color Model:    RGB
  Color Space:    srgb
  Channel Depth:  8 x 3 (24 bpp)

A:
  Data:           16 bit float
  Color Model:    Single Channel
  Channel Depth:  16 x 1 (16 bpp)
"""

TEXTURES_TEXT = """File:           /path/a.rat (RAT format)
Resolution:     256 x 256
Data:           8 bit integer

Unable to open '/path/bad.png'

File:           /path/b.hdr (RADIANCE format)
Resolution:     2048 x 1024
Data:           32 bit float

File:           /path/c.exr (oiio format)
Resolution:     1024 x 2100
Data Window:    (0,0)-(1023,2099)
"""

BGEO_TEXT = """          artist - sidefx
            date - 2026-10-08 02:01:05
        hostname - sidefx.com
        software - Houdini 22.0.466
____________________________________________________________
4,564 Points
11,772 Vertices
2,660 Primitives
      2,660 Polygons
____________________________________________________________
     2 point attributes:\tP, uv
     1 primitive attributes:\tCd
____________________________________________________________
  Size: 3.9003, 1.02138, 0.0725432
Center: 0.0332, 0.0040285, 0.0053526
Bounds: -1.91695, -0.50666, -0.030919
        1.98335 0.514717 0.0416242
"""

MIXED_TEXT = """        software - Houdini 22.0.466
____________________________________________________________
7 Points
9 Vertices
8 Primitives
          6 Packed Geometries
          2 Polygons
____________________________________________________________
     1 vertex attributes:\tN
     1 point attributes:\tP
     1 global attributes:\tnote
____________________________________________________________
  Size: 10, 1, 10
"""

OBJ_TEXT = """40,401 Points
160,000 Vertices
40,000 Primitives
____________________________________________________________
  Size: 1.31226, 2.02345, 1.41044
Center: 0.0361055, 0.083493, -0.0474995
"""


class TheImageParser(unittest.TestCase):
    """Plain `iinfo` output to rows, on the texts measured on Houdini 22.0.466."""

    def test_an_exr(self):
        self.assertEqual(file_info.parse_image(EXR_TEXT), [
            ("Dimensions", "64 x 64"), ("Color Space", "Linear"), ("Bit Depth", "16 bit float"),
            ("Channels", "RGBA"), ("Compression", "ZIP"), ("MIP Maps", "Yes")])

    def test_a_rat_has_mip_maps_from_its_resolutions_line(self):
        self.assertEqual(file_info.parse_image(RAT_TEXT), [
            ("Dimensions", "256 x 256"), ("Color Space", "sRGB"), ("Bit Depth", "8 bit integer"),
            ("Channels", "RGBA"), ("MIP Maps", "Yes")])

    def test_a_pic_uses_its_first_plane(self):
        self.assertEqual(file_info.parse_image(PIC_TEXT), [
            ("Dimensions", "256 x 256"), ("Color Space", "sRGB"), ("Bit Depth", "8 bit integer"),
            ("Channels", "RGB")])

    def test_an_exr_without_mip_maps(self):
        rows = dict(file_info.parse_image(EXR_TEXT.replace("true", "false")))
        self.assertEqual(rows["MIP Maps"], "No")

    def test_another_color_space_is_shown_as_reported(self):
        text = EXR_TEXT.replace("linear", "opencolorio (lin_rec709)")
        self.assertEqual(dict(file_info.parse_image(text))["Color Space"],
                         "opencolorio (lin_rec709)")

    def test_a_file_iinfo_cannot_open_has_no_rows(self):
        self.assertEqual(file_info.parse_image("Unable to open '/path/x.png'\n"), [])


class TheTexturesParser(unittest.TestCase):
    """Several files in one `iinfo` call: the largest by pixel count."""

    def test_the_largest_by_pixels_not_by_width(self):
        self.assertEqual(file_info.parse_largest(TEXTURES_TEXT),
                         [("Largest Texture", "1024 x 2100")])

    def test_no_resolution_gives_no_row(self):
        self.assertEqual(file_info.parse_largest("Unable to open '/path/x.png'\n"), [])


class TheGeometryParser(unittest.TestCase):
    """`ginfo -S` output to rows."""

    def test_a_bgeo(self):
        self.assertEqual(file_info.parse_geometry(BGEO_TEXT), [
            ("Points", "4,564"), ("Vertices", "11,772"), ("Primitives", "2,660 Polygons"),
            ("Attributes", "P, uv, Cd"), ("Dimensions", "3.9 x 1.02 x 0.07"),
            ("Saved With", "Houdini 22.0.466")])

    def test_several_primitive_types_and_every_attribute_class_in_order(self):
        self.assertEqual(file_info.parse_geometry(MIXED_TEXT), [
            ("Points", "7"), ("Vertices", "9"),
            ("Primitives", "8 (6 Packed Geometries, 2 Polygons)"),
            ("Attributes", "P, N, note"), ("Dimensions", "10 x 1 x 10"),
            ("Saved With", "Houdini 22.0.466")])

    def test_an_obj_gives_counts_and_size(self):
        self.assertEqual(file_info.parse_geometry(OBJ_TEXT), [
            ("Points", "40,401"), ("Vertices", "160,000"), ("Primitives", "40,000"),
            ("Dimensions", "1.31 x 2.02 x 1.41")])

    def test_a_file_ginfo_cannot_open_has_no_rows(self):
        self.assertEqual(file_info.parse_geometry("Unable to open: '/path/x.bgeo'\n"), [])


class TheTextHelpers(unittest.TestCase):
    """`size_text`, `date_text`, `format_text`."""

    def test_size_text(self):
        self.assertEqual(file_info.size_text(512), "512 B")
        self.assertEqual(file_info.size_text(840 * 1024), "840 KB")
        self.assertEqual(file_info.size_text(int(12.4 * 1024 ** 2)), "12.4 MB")
        self.assertEqual(file_info.size_text(int(1.3 * 1024 ** 3)), "1.3 GB")
        self.assertEqual(file_info.size_text(-5), "0 B")

    def test_date_text_is_local_time(self):
        stamp = time.mktime((2021, 8, 10, 12, 0, 0, 0, 0, -1))
        self.assertEqual(file_info.date_text(stamp), "2021-08-10")

    def test_format_text(self):
        self.assertEqual(file_info.format_text("/a/b.exr"), "EXR")
        self.assertEqual(file_info.format_text("/a/b.bgeo.sc"), "BGEO.SC")
        self.assertEqual(file_info.format_text("/a/b.HIPLC"), "HIPLC")
        self.assertEqual(file_info.format_text("/a/README"), "")


class TheFileRows(unittest.TestCase):
    """`file_rows` from one `os.stat`."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="amaze_file_info_")
        self.addCleanup(shutil.rmtree, self.folder, True)

    def test_an_existing_file(self):
        path = os.path.join(self.folder, "rock.bgeo.sc")
        with open(path, "wb") as handle:
            handle.write(b"x" * 2048)
        before, after = file_info.file_rows(path)
        labels = [label for label, _value in before]
        self.assertEqual(before[0], ("Name", "rock"))
        self.assertIn(("Size", "2 KB"), before)
        self.assertEqual(before[-1], ("Format", "BGEO.SC"))
        self.assertIn("Modified", labels)
        self.assertEqual(after, (("Folder", self.folder),))

    def test_a_missing_file_has_its_name_format_and_folder_only(self):
        path = os.path.join(self.folder, "gone.exr")
        before, after = file_info.file_rows(path)
        self.assertEqual(before, (("Name", "gone"), ("Format", "EXR")))
        self.assertEqual(after, (("Folder", self.folder),))


class TheRequestForAFile(unittest.TestCase):
    """Which read a file gets, by its ending."""

    def test_the_kinds(self):
        for name, kind in (("a.exr", "image"), ("a.RAT", "image"), ("a.tif", "image"),
                           ("a.tx", "image"), ("a.bgeo.sc", "geometry"),
                           ("a.bgeo.gz", "geometry"), ("a.geo", "geometry"),
                           ("a.obj", "geometry"), ("a.usda", "usd"), ("a.usdz", "usd")):
            self.assertEqual(file_info.request_for_file("/x/" + name),
                             file_info.Request(kind, ("/x/" + name,)), name)

    def test_no_read(self):
        for name in ("a.hip", "a.hiplc", "a.hipnc", "a.psd", "a.abc", "a.dng", "README"):
            self.assertIsNone(file_info.request_for_file("/x/" + name), name)

    def test_textures_and_sizes_skip_empty_paths(self):
        self.assertIsNone(file_info.request_for_textures(["", None]))
        self.assertEqual(file_info.request_for_sizes(["", "/a"]),
                         file_info.Request("sizes", ("/a",)))


class _FakeHoudini:
    """A folder with an empty `bin/iinfo` and `bin/ginfo`, so `bundled_binary` finds them."""

    def __init__(self, testcase, tools=("iinfo", "ginfo")):
        self.hfs = tempfile.mkdtemp(prefix="amaze_fake_hfs_")
        testcase.addCleanup(shutil.rmtree, self.hfs, True)
        os.mkdir(os.path.join(self.hfs, "bin"))
        for tool in tools:
            open(os.path.join(self.hfs, "bin", tool), "w").close()


class ReadWithAFakeRunner(unittest.TestCase):
    """`read` per kind, with `run_tool` replaced, so the tools are not needed."""

    def setUp(self):
        self.hfs = _FakeHoudini(self).hfs
        self.calls = []

    def _runner(self, text):
        def fake(program, args, cancelled):
            self.calls.append((os.path.basename(program), list(args)))
            return text
        return mock.patch.object(file_info, "run_tool", fake)

    def test_image(self):
        with self._runner(RAT_TEXT):
            rows = file_info.read(file_info.Request("image", ("/x/a.rat",)), self.hfs)
        self.assertEqual(rows[0], ("Dimensions", "256 x 256"))
        self.assertEqual(self.calls, [("iinfo", ["/x/a.rat"])])

    def test_geometry(self):
        with self._runner(BGEO_TEXT):
            rows = file_info.read(file_info.Request("geometry", ("/x/a.bgeo",)), self.hfs)
        self.assertEqual(rows[0], ("Points", "4,564"))
        self.assertEqual(self.calls, [("ginfo", ["-S", "/x/a.bgeo"])])

    def test_textures_skip_missing_files_and_call_in_batches(self):
        folder = tempfile.mkdtemp(prefix="amaze_textures_")
        self.addCleanup(shutil.rmtree, folder, True)
        paths = []
        for number in range(file_info.PATHS_PER_CALL + 5):
            paths.append(os.path.join(folder, "t%d.png" % number))
            open(paths[-1], "w").close()
        missing = os.path.join(folder, "missing.png")
        with self._runner(TEXTURES_TEXT):
            rows = file_info.read(file_info.Request("textures", tuple([missing] + paths)),
                                  self.hfs)
        self.assertEqual(rows, [("Largest Texture", "1024 x 2100")])
        self.assertEqual([len(args) for _tool, args in self.calls],
                         [file_info.PATHS_PER_CALL, 5])
        self.assertNotIn(missing, self.calls[0][1])

    def test_textures_with_no_existing_file_run_nothing(self):
        with self._runner(TEXTURES_TEXT):
            rows = file_info.read(file_info.Request("textures", ("/no/such.png",)), self.hfs)
        self.assertEqual((rows, self.calls), ([], []))

    def test_sizes(self):
        folder = tempfile.mkdtemp(prefix="amaze_sizes_")
        self.addCleanup(shutil.rmtree, folder, True)
        paths = []
        for number, size in enumerate((1024, 2048)):
            paths.append(os.path.join(folder, "f%d" % number))
            with open(paths[-1], "wb") as handle:
                handle.write(b"x" * size)
        request = file_info.Request("sizes", tuple(paths + [os.path.join(folder, "gone")]))
        self.assertEqual(file_info.read(request), [("Size", "3 KB")])
        self.assertEqual(file_info.read(file_info.Request("sizes", ("/no/such",))), [])

    def test_alembic_has_no_rows(self):
        with self._runner(RAT_TEXT):
            rows = file_info.read(file_info.Request("alembic", ("/x/a.abc",)), self.hfs)
        self.assertEqual((rows, self.calls), ([], []))

    def test_a_missing_tool_gives_no_rows(self):
        empty = _FakeHoudini(self, tools=()).hfs
        with self._runner(RAT_TEXT):
            rows = file_info.read(file_info.Request("image", ("/x/a.rat",)), empty)
        self.assertEqual((rows, self.calls), ([], []))

    def test_a_tool_that_answers_nothing_gives_no_rows(self):
        with self._runner(None):
            rows = file_info.read(file_info.Request("image", ("/x/a.rat",)), self.hfs)
        self.assertEqual(rows, [])

    def test_a_cancelled_read_gives_no_rows(self):
        with self._runner(RAT_TEXT):
            rows = file_info.read(file_info.Request("image", ("/x/a.rat",)), self.hfs,
                                  cancelled=lambda: True)
        self.assertEqual(rows, [])

    def test_a_raising_reader_gives_no_rows(self):
        def broken(program, args, cancelled):
            raise ValueError("broken")
        with mock.patch.object(file_info, "run_tool", broken):
            rows = file_info.read(file_info.Request("image", ("/x/a.rat",)), self.hfs)
        self.assertEqual(rows, [])

    def test_a_usd_file_usd_cannot_open_gives_no_rows(self):
        folder = tempfile.mkdtemp(prefix="amaze_usd_")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "bad.usda")
        test_support.write_text(path, "not usd\n")
        self.assertEqual(file_info.read(file_info.Request("usd", (path,))), [])


class _FakeFormat:
    """A pixel type as OpenImageIO names it, with its size in bytes."""

    def __init__(self, name, size):
        self._name, self._size = name, size

    def size(self):
        return self._size

    def __str__(self):
        return self._name


class _FakeSpec:
    """The part of an OpenImageIO `ImageSpec` that `header_rows` reads."""

    def __init__(self, width, height, pixel, size, names, **attributes):
        self.width, self.height, self.channelnames = width, height, tuple(names)
        self.format = _FakeFormat(pixel, size)
        self._attributes = {key.replace("__", ":"): value for key, value in attributes.items()}

    def get_string_attribute(self, name, default=""):
        return str(self._attributes.get(name, default))

    def get_int_attribute(self, name, default=0):
        return int(self._attributes.get(name, default))


class _FakeSource:
    """An opened picture with `levels` MIP levels; None for levels gives a thousand of them."""

    def __init__(self, spec, reader="openexr", levels=1):
        self._spec, self._reader, self._levels = spec, reader, levels
        self.seeks, self.closed = 0, False

    def spec(self):
        return self._spec

    def format_name(self):
        return self._reader

    def seek_subimage(self, part, level):
        self.seeks += 1
        return part == 0 and level < (1000 if self._levels is None else self._levels)

    def close(self):
        self.closed = True


class TheHeaderRows(unittest.TestCase):
    """An opened picture's header to rows, without OpenImageIO."""

    def test_an_exr_with_one_level(self):
        spec = _FakeSpec(800, 600, "half", 2, "RGBA", oiio__ColorSpace="Linear", compression="zip")
        self.assertEqual(file_info.header_rows(_FakeSource(spec)), [
            ("Dimensions", "800 x 600"), ("Color Space", "Linear"), ("Bit Depth", "16 bit float"),
            ("Channels", "RGBA"), ("Compression", "ZIP"), ("MIP Maps", "No")])

    def test_an_exr_with_mip_levels(self):
        spec = _FakeSpec(2048, 1024, "float", 4, "RGB", compression="dwaa")
        rows = dict(file_info.header_rows(_FakeSource(spec, levels=12)))
        self.assertEqual((rows["MIP Maps"], rows["Bit Depth"], rows["Compression"]),
                         ("Yes", "32 bit float", "DWAA"))

    def test_a_tiff_has_a_mip_row_only_with_levels(self):
        spec = _FakeSpec(8, 8, "uint16", 2, "RGB", oiio__BitsPerSample=16, compression="lzw")
        self.assertEqual(file_info.header_rows(_FakeSource(spec, reader="tiff")), [
            ("Dimensions", "8 x 8"), ("Bit Depth", "16 bit integer"), ("Channels", "RGB"),
            ("Compression", "LZW")])
        rows = file_info.header_rows(_FakeSource(spec, reader="tiff", levels=4))
        self.assertEqual(rows[-1], ("MIP Maps", "Yes"))

    def test_the_bits_the_file_states_are_shown_not_the_stored_size(self):
        spec = _FakeSpec(8, 8, "uint16", 2, "RGB", oiio__BitsPerSample=10)
        self.assertEqual(dict(file_info.header_rows(_FakeSource(spec, reader="dpx")))["Bit Depth"],
                         "10 bit integer")

    def test_longer_channel_names_are_listed_with_commas(self):
        spec = _FakeSpec(8, 8, "half", 2, ("R", "G", "B", "depth.Z"))
        self.assertEqual(dict(file_info.header_rows(_FakeSource(spec)))["Channels"],
                         "R, G, B, depth.Z")
        five = _FakeSpec(8, 8, "half", 2, "RGBAZ")
        self.assertEqual(dict(file_info.header_rows(_FakeSource(five)))["Channels"], "RGBAZ")

    def test_an_uncompressed_file_reads_none(self):
        spec = _FakeSpec(8, 8, "float", 4, "RGB", compression="none")
        self.assertEqual(dict(file_info.header_rows(_FakeSource(spec)))["Compression"], "None")

    def test_a_color_space_is_shown_as_the_header_names_it(self):
        for stated, shown in (("lin_srgb", "lin_srgb"), ("Linear Rec.709 (sRGB)",
                                                         "Linear Rec.709 (sRGB)"),
                              ("sRGB", "sRGB"), ("linear", "Linear")):
            spec = _FakeSpec(8, 8, "uint8", 1, "RGB", oiio__ColorSpace=stated)
            rows = dict(file_info.header_rows(_FakeSource(spec, reader="targa")))
            self.assertEqual(rows["Color Space"], shown)

    def test_the_level_count_ends_at_its_limit(self):
        source = _FakeSource(_FakeSpec(8, 8, "half", 2, "RGB"), levels=None)
        self.assertEqual(file_info.header_rows(source)[-1], ("MIP Maps", "Yes"))
        self.assertEqual(source.seeks, file_info.MIP_LEVEL_LIMIT)


class ReadThroughTheHeader(unittest.TestCase):
    """`read` asks the header first and runs `iinfo` only for a picture without a reader."""

    def setUp(self):
        self.hfs = _FakeHoudini(self).hfs
        self.calls, self.sources = [], {}
        self.folder = tempfile.mkdtemp(prefix="amaze_header_")
        self.addCleanup(shutil.rmtree, self.folder, True)
        for patch in (mock.patch.object(file_info, "run_tool", self._run_tool),
                      mock.patch.object(file_info, "open_header", self.sources.get)):
            patch.start()
            self.addCleanup(patch.stop)

    def _run_tool(self, program, args, cancelled):
        self.calls.append((os.path.basename(program), list(args)))
        return RAT_TEXT

    def _file(self, name, width=0, height=0):
        """An empty file; with a size, one whose header the fake reader opens."""
        path = os.path.join(self.folder, name)
        open(path, "w").close()
        if width:
            self.sources[path] = _FakeSource(_FakeSpec(width, height, "uint8", 1, "RGB"), "png")
        return path

    def test_a_picture_with_a_reader_runs_no_tool_and_is_closed(self):
        path = self._file("a.png", 32, 16)
        rows = file_info.read(file_info.Request("image", (path,)), self.hfs)
        self.assertEqual(rows, [("Dimensions", "32 x 16"), ("Bit Depth", "8 bit integer"),
                                ("Channels", "RGB")])
        self.assertEqual(self.calls, [])
        self.assertTrue(self.sources[path].closed)

    def test_a_picture_without_a_reader_goes_to_iinfo(self):
        path = self._file("a.rat")
        rows = file_info.read(file_info.Request("image", (path,)), self.hfs)
        self.assertEqual(rows[0], ("Dimensions", "256 x 256"))
        self.assertEqual(self.calls, [("iinfo", [path])])

    def test_a_header_that_cannot_be_read_gives_no_rows_and_is_closed(self):
        path = self._file("a.png", 32, 16)
        self.sources[path].spec = mock.Mock(side_effect=RuntimeError("broken header"))
        self.assertEqual(file_info.read(file_info.Request("image", (path,)), self.hfs), [])
        self.assertTrue(self.sources[path].closed)

    def test_textures_send_only_the_pictures_without_a_reader_to_iinfo(self):
        small, rat = self._file("small.png", 64, 64), self._file("a.rat")
        wide = self._file("wide.exr", 1024, 100)
        rows = file_info.read(file_info.Request("textures", (small, rat, wide)), self.hfs)
        self.assertEqual(rows, [("Largest Texture", "1024 x 100")])
        self.assertEqual(self.calls, [("iinfo", [rat])])
        self.assertTrue(self.sources[small].closed and self.sources[wide].closed)

    def test_the_largest_can_be_the_one_iinfo_read(self):
        small, rat = self._file("small.png", 64, 64), self._file("a.rat")
        rows = file_info.read(file_info.Request("textures", (small, rat)), self.hfs)
        self.assertEqual(rows, [("Largest Texture", "256 x 256")])

    def test_textures_that_all_have_a_reader_run_no_tool(self):
        paths = (self._file("a.png", 64, 64), self._file("b.png", 128, 48))
        rows = file_info.read(file_info.Request("textures", paths), self.hfs)
        self.assertEqual((rows, self.calls), ([("Largest Texture", "128 x 48")], []))


def _openimageio():
    """Houdini's OpenImageIO module, or None where its Python has none."""
    try:
        import OpenImageIO
    except ImportError:
        return None
    return OpenImageIO


@unittest.skipIf(_openimageio() is None, "this Python has no OpenImageIO")
class TheRealHeader(unittest.TestCase):
    """`read` with OpenImageIO itself, on pictures it writes here; no tool may run."""

    def setUp(self):
        self.oiio = _openimageio()
        self.folder = tempfile.mkdtemp(prefix="amaze_oiio_")
        self.addCleanup(shutil.rmtree, self.folder, True)
        patch = mock.patch.object(file_info, "run_tool",
                                  mock.Mock(side_effect=AssertionError("a tool was run")))
        patch.start()
        self.addCleanup(patch.stop)

    def _picture(self, name, width, height, channels, pixel, **attributes):
        """Write a flat picture of that size and pixel type and return its path."""
        spec = self.oiio.ImageSpec(width, height, channels, pixel)
        for key, value in attributes.items():
            spec.attribute(key, value)
        buffer = self.oiio.ImageBuf(spec)
        self.oiio.ImageBufAlgo.fill(buffer, (0.5,) * channels)
        path = os.path.join(self.folder, name)
        self.assertTrue(buffer.write(path), buffer.geterror())
        return path

    def _rows(self, path):
        return dict(file_info.read(file_info.request_for_file(path)))

    def test_a_png(self):
        rows = self._rows(self._picture("a.png", 8, 4, 4, "uint8"))
        self.assertEqual((rows["Dimensions"], rows["Bit Depth"], rows["Channels"]),
                         ("8 x 4", "8 bit integer", "RGBA"))
        self.assertNotIn("MIP Maps", rows)

    def test_an_exr_without_mip_levels(self):
        rows = self._rows(self._picture("b.exr", 16, 8, 3, "half", compression="zip"))
        self.assertEqual(rows, {"Dimensions": "16 x 8", "Color Space": "Linear",
                                "Bit Depth": "16 bit float", "Channels": "RGB",
                                "Compression": "ZIP", "MIP Maps": "No"})

    def test_a_16_bit_tiff(self):
        rows = self._rows(self._picture("c.tif", 8, 8, 3, "uint16", compression="lzw"))
        self.assertEqual((rows["Bit Depth"], rows["Compression"]), ("16 bit integer", "LZW"))

    def test_a_mip_mapped_texture(self):
        source = self.oiio.ImageBuf(self.oiio.ImageSpec(64, 64, 3, "half"))
        self.oiio.ImageBufAlgo.fill(source, (0.2, 0.4, 0.6))
        for name in ("e.tx", "f.exr"):
            path = os.path.join(self.folder, name)
            self.assertTrue(self.oiio.ImageBufAlgo.make_texture(
                self.oiio.MakeTxTexture, source, path), name)
            rows = self._rows(path)
            self.assertEqual((rows["Dimensions"], rows["MIP Maps"]), ("64 x 64", "Yes"), name)

    def test_the_largest_of_several_textures(self):
        paths = (self._picture("a.png", 8, 4, 3, "uint8"), self._picture("b.exr", 16, 8, 3, "half"),
                 os.path.join(self.folder, "missing.png"))
        self.assertEqual(file_info.read(file_info.request_for_textures(paths)),
                         [("Largest Texture", "16 x 8")])

    def test_a_file_that_is_no_picture_has_no_reader(self):
        path = os.path.join(self.folder, "text.png")
        test_support.write_text(path, "not a picture\n")
        self.assertIsNone(file_info.open_header(path))
        self.assertIsNone(file_info.open_header(os.path.join(self.folder, "missing.png")))
        self.assertIsNone(file_info.header_size(path))


class WithoutOpenImageIO(unittest.TestCase):
    """A Python that cannot import OpenImageIO reads every picture through `iinfo`."""

    def test_no_module_means_no_reader(self):
        with mock.patch.dict(sys.modules, {"OpenImageIO": None}):    # None makes the import fail
            self.assertIsNone(file_info.open_header("/x/a.exr"))
            self.assertIsNone(file_info.header_size("/x/a.exr"))


@unittest.skipIf(hostos.is_windows(), "the stand-in tool is a shell script")
class TheRunner(unittest.TestCase):
    """`run_tool` returns stdout, and stops a tool on timeout or cancel."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="amaze_runner_")
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.pid_file = os.path.join(self.folder, "pid")
        self.tool = os.path.join(self.folder, "slow")
        test_support.write_text(self.tool, "#!/bin/sh\necho $$ > '%s'\nexec sleep 30\n"
                                % self.pid_file)
        os.chmod(self.tool, os.stat(self.tool).st_mode | stat.S_IXUSR)

    def _assert_gone(self):
        with open(self.pid_file) as handle:
            pid = int(handle.read())
        with self.assertRaises(OSError):
            os.kill(pid, 0)

    def test_stdout_at_any_exit_code(self):
        self.assertEqual(file_info.run_tool("/bin/sh", ["-c", "echo out; echo err >&2; exit 1"],
                                            lambda: False), "out\n")

    def test_a_tool_past_its_timeout_is_killed(self):
        start = time.monotonic()
        with mock.patch.object(file_info, "TOOL_TIMEOUT_SECONDS", 0.5):
            self.assertIsNone(file_info.run_tool(self.tool, [], lambda: False))
        self.assertLess(time.monotonic() - start, 3.0)
        self._assert_gone()

    def _started(self):
        """True once the stand-in tool has written its pid, which a loaded machine delays."""
        try:
            return os.path.getsize(self.pid_file) > 0
        except OSError:
            return False

    def test_a_cancelled_tool_is_killed(self):
        start = time.monotonic()
        self.assertIsNone(file_info.run_tool(self.tool, [], self._started))
        self.assertLess(time.monotonic() - start, 3.0)
        self._assert_gone()

    def test_a_timeout_inside_read_gives_no_rows(self):
        hfs = _FakeHoudini(self, tools=()).hfs
        shutil.copy(self.tool, os.path.join(hfs, "bin", "iinfo"))
        with mock.patch.object(file_info, "TOOL_TIMEOUT_SECONDS", 0.5):
            self.assertEqual(file_info.read(file_info.Request("image", ("/x/a.rat",)), hfs), [])
        self._assert_gone()

    def test_a_program_that_cannot_start(self):
        self.assertIsNone(file_info.run_tool(os.path.join(self.folder, "none"), [],
                                             lambda: False))


_HFS = os.environ.get("HFS", "")


@unittest.skipIf(hostos.bundled_binary(_HFS, "iinfo") is None
                 or hostos.bundled_binary(_HFS, "ginfo") is None,
                 "this $HFS has no iinfo or ginfo")
class TheRealTools(unittest.TestCase):
    """`read` with Houdini's own `iinfo`, `ginfo` and `pxr` on Houdini's sample files."""

    def _sample(self, *parts):
        path = os.path.join(_HFS, "houdini", *parts)
        if not os.path.isfile(path):
            self.skipTest("no sample %s" % path)
        return path

    def test_a_rat(self):
        path = self._sample("pic", "Mandril.rat")
        self.assertEqual(file_info.read(file_info.request_for_file(path)), [
            ("Dimensions", "256 x 256"), ("Color Space", "sRGB"), ("Bit Depth", "8 bit integer"),
            ("Channels", "RGBA"), ("MIP Maps", "Yes")])

    @unittest.skipIf(_openimageio() is None, "this Python has no OpenImageIO")
    def test_a_scanline_exr_has_no_mip_maps(self):
        path = self._sample("pic", "linearly_transformed_cosines", "GGX", "amplitudes.exr")
        self.assertEqual(file_info.read(file_info.request_for_file(path)), [
            ("Dimensions", "64 x 64"), ("Color Space", "Linear"), ("Bit Depth", "16 bit float"),
            ("Channels", "RGBA"), ("Compression", "ZIP"), ("MIP Maps", "No")])

    @unittest.skipIf(_openimageio() is None, "this Python has no OpenImageIO")
    def test_a_mip_mapped_exr(self):
        rows = dict(file_info.read(file_info.request_for_file(
            self._sample("pic", "lookdev", "envmap.exr"))))
        self.assertEqual((rows["Dimensions"], rows["MIP Maps"]), ("2048 x 1024", "Yes"))

    def test_the_largest_of_several_textures(self):
        paths = (self._sample("pic", "Mandril.rat"), self._sample("pic", "Mandril.pic"),
                 self._sample("pic", "linearly_transformed_cosines", "GGX", "amplitudes.exr"))
        self.assertEqual(file_info.read(file_info.request_for_textures(paths)),
                         [("Largest Texture", "256 x 256")])

    def test_a_saved_box(self):
        folder = tempfile.mkdtemp(prefix="amaze_ginfo_")
        self.addCleanup(shutil.rmtree, folder, True)
        geometry = hou.Geometry()
        hou.sopNodeTypeCategory().nodeVerbs()["box"].execute(geometry, [])
        for ending in (".bgeo.sc", ".bgeo.gz", ".geo"):
            path = os.path.join(folder, "box" + ending)
            geometry.saveToFile(path)
            rows = dict(file_info.read(file_info.request_for_file(path)))
            self.assertEqual((rows["Points"], rows["Vertices"], rows["Primitives"],
                              rows["Attributes"], rows["Dimensions"]),
                             ("8", "24", "6 Polygons", "P", "1 x 1 x 1"), ending)
            self.assertTrue(rows["Saved With"].startswith("Houdini "), ending)

    def test_a_usd_stage(self):
        path = self._sample("usd", "assets", "templatehead", "mtl.usdc")
        self.assertEqual(file_info.read(file_info.request_for_file(path)), [
            ("Prims", "1"), ("Layers", "2"), ("Default Prim", "/templatehead"),
            ("Up Axis", "Y"), ("Meters Per Unit", "1")])

    def test_a_usd_frame_range(self):
        folder = tempfile.mkdtemp(prefix="amaze_usd_")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "shot.usda")
        test_support.write_text(path, '#usda 1.0\n(\n    startTimeCode = 1\n'
                                '    endTimeCode = 240\n    timeCodesPerSecond = 24\n'
                                '    upAxis = "Z"\n    metersPerUnit = 0.01\n)\n'
                                'def Xform "a"\n{\n    def Xform "b" {}\n}\n')
        self.assertEqual(file_info.read(file_info.request_for_file(path)), [
            ("Prims", "2"), ("Layers", "2"), ("Up Axis", "Z"), ("Meters Per Unit", "0.01"),
            ("Frames", "1 - 240, 24 fps")])


class _Gate:
    """A stand-in for `read` that blocks until released or cancelled, and records each call."""

    def __init__(self):
        self.calls = []    # (request, event set once the read saw its cancel)
        self.release = threading.Event()

    def __call__(self, request, hfs="", cancelled=None):
        seen = threading.Event()
        self.calls.append((request, seen))
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not self.release.is_set():
            if cancelled():
                seen.set()
                return []
            time.sleep(0.01)
        return [("Path", request.paths[0])]


class TheReader(unittest.TestCase):
    """`Reader`: the newest ask wins, `stop()` silences, deletion mid-read is survived."""

    def setUp(self):
        self.gate = _Gate()
        patch = mock.patch.object(file_info, "read", self.gate)
        patch.start()
        self.addCleanup(patch.stop)    # cleanups run last first: release, wait, then unpatch
        self.addCleanup(test_support.pump_until, lambda: not file_info.engine._threads, 5.0)
        self.addCleanup(self.gate.release.set)
        self.got = []

    def _reader(self):
        reader = file_info.Reader()
        reader.ready.connect(lambda key, rows: self.got.append((key, rows)))
        return reader

    def test_the_newest_key_wins(self):
        reader = self._reader()
        reader.ask("a", file_info.Request("sizes", ("/a",)))
        test_support.pump_until(lambda: len(self.gate.calls) == 1, 2.0)
        reader.ask("b", file_info.Request("sizes", ("/b",)))
        self.assertTrue(test_support.pump_until(lambda: len(self.gate.calls) == 2, 2.0))
        self.assertTrue(self.gate.calls[0][1].wait(2.0), "the older read saw no cancel")
        self.gate.release.set()
        self.assertTrue(test_support.pump_until(lambda: self.got, 3.0))
        test_support.pump_until(lambda: not file_info.engine._threads, 3.0)
        self.assertEqual(self.got, [("b", [("Path", "/b")])])

    def test_an_answer_is_emitted_on_the_ui_thread(self):
        reader = file_info.Reader()
        threads = []
        reader.ready.connect(lambda key, rows: threads.append(threading.current_thread()))
        self.gate.release.set()
        reader.ask("a", file_info.Request("sizes", ("/a",)))
        self.assertTrue(test_support.pump_until(lambda: threads, 3.0))
        self.assertIs(threads[0], threading.main_thread())

    def test_stop_emits_nothing(self):
        reader = self._reader()
        reader.ask("a", file_info.Request("sizes", ("/a",)))
        test_support.pump_until(lambda: self.gate.calls, 2.0)
        reader.stop()
        self.assertTrue(self.gate.calls[0][1].wait(2.0), "the read saw no cancel")
        self.gate.release.set()
        test_support.pump_until(lambda: not file_info.engine._threads, 3.0)
        test_support.pump_until(lambda: False, 0.2)
        self.assertEqual(self.got, [])

    def test_deleting_the_reader_mid_read(self):
        reader = self._reader()
        reader.ask("a", file_info.Request("sizes", ("/a",)))
        test_support.pump_until(lambda: self.gate.calls, 2.0)
        del reader
        gc.collect()
        self.assertTrue(self.gate.calls[0][1].wait(2.0), "the read saw no cancel")
        self.assertTrue(test_support.pump_until(lambda: not file_info.engine._threads, 3.0))
        test_support.pump_until(lambda: False, 0.2)
        self.assertEqual(self.got, [])

    def test_delete_later_mid_read(self):
        reader = self._reader()
        destroyed = []
        reader.destroyed.connect(lambda: destroyed.append(True))
        reader.ask("a", file_info.Request("sizes", ("/a",)))
        test_support.pump_until(lambda: self.gate.calls, 2.0)
        reader.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        self.assertTrue(destroyed)
        self.assertTrue(self.gate.calls[0][1].wait(2.0), "the read saw no cancel")
        self.gate.release.set()
        self.assertTrue(test_support.pump_until(lambda: not file_info.engine._threads, 3.0))
        test_support.pump_until(lambda: False, 0.2)
        self.assertEqual(self.got, [])

    def test_the_engine_shutdown_on_quit_stops_a_running_read(self):
        reader = self._reader()
        reader.ask("a", file_info.Request("sizes", ("/a",)))
        test_support.pump_until(lambda: self.gate.calls, 2.0)
        start = time.monotonic()
        file_info.engine.shutdown()
        self.assertLess(time.monotonic() - start, 2.0)
        self.assertTrue(self.gate.calls[0][1].is_set())
        test_support.pump_until(lambda: False, 0.2)
        self.assertEqual(self.got, [])
        self.gate.release.set()
        reader.ask("b", file_info.Request("sizes", ("/b",)))
        self.assertTrue(test_support.pump_until(lambda: self.got, 3.0))
        self.assertEqual(self.got, [("b", [("Path", "/b")])])


if __name__ == "__main__":
    unittest.main()
