"""The SimReady source, from the release listing to a built material. ▸r/simready-release"""

import io
import os
import re
import shutil
import struct
import sys
import tempfile
import unittest
import urllib.error
import zipfile
import zlib
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.tests import test_support  # noqa: E402
from amaze.tests.test_packages import _ranged_server, _Served  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "simready")
BASE = ("https://github.com/NVIDIA-Omniverse/PhysicalAI-SimReady-Materials/"
        "releases/download/v9/")
BIG = 300 * 1024    # one texture spans several blocks, so a split can land inside it


def _read(*parts) -> bytes:
    with open(os.path.join(FIXTURES, *parts), "rb") as handle:
        return handle.read()


def _textures(category, name) -> dict:
    """{member: bytes} for every texture the fixture material names, the first one BIG."""
    text = _read("Materials", category, name + ".usda").decode("utf-8")
    found, members = re.findall(r"_texture_file = @([^@]+)@", text), {}
    for n, ref in enumerate(found):
        member = os.path.normpath("Materials/%s/%s" % (category, ref)).replace(os.sep, "/")
        members[member] = bytes((n + i) % 251 for i in range(BIG if n == 0 else 4096))
    return members


def _archive(category, names, drop=()) -> bytes:
    """A category zip laid out as the release lays it out; `drop` leaves members out."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as bundle:
        for name in names:
            bundle.writestr("Materials/%s/%s.usda" % (category, name),
                            _read("Materials", category, name + ".usda"),
                            zipfile.ZIP_DEFLATED)
            for member, data in _textures(category, name).items():
                if member not in drop:
                    bundle.writestr(member, data)    # stored, as jpgs barely compress
        bundle.writestr("Materials/%s/LICENSE.md" % category, _read("LICENSE.md"))
        bundle.writestr("open_pbr_uber_base_class.usda",
                        _read("open_pbr_uber_base_class.usda"), zipfile.ZIP_DEFLATED)
    return out.getvalue()


def _split(blob: bytes, at: int):
    """`blob` as `zip -s` writes it: a spanning marker, two parts, the directory in the last."""
    end = blob.rfind(b"PK\x05\x06")
    size, offset = struct.unpack("<II", blob[end + 12:end + 20])
    assert at < offset, "the split must leave the directory whole in the last part"
    directory, p = bytearray(blob[offset:offset + size]), 0
    while p < len(directory):
        name, extra, comment = struct.unpack("<HHH", directory[p + 28:p + 34])
        header = struct.unpack("<I", directory[p + 42:p + 46])[0]
        first = header < at
        struct.pack_into("<H", directory, p + 34, 0 if first else 1)
        struct.pack_into("<I", directory, p + 42, header + 4 if first else header - at)
        p += 46 + name + extra + comment
    record = bytearray(blob[end:])
    struct.pack_into("<HH", record, 4, 1, 1)
    struct.pack_into("<I", record, 16, offset - at)
    return b"PK\x07\x08" + blob[:at], blob[at:offset] + bytes(directory) + bytes(record)


def _inside_big(blob: bytes, category: str) -> int:
    """A byte inside the first material's BIG texture - where the split goes."""
    with zipfile.ZipFile(io.BytesIO(blob)) as bundle:
        big = max(bundle.infolist(), key=lambda info: info.compress_size)
        assert big.compress_size == BIG and category in big.filename
        return big.header_offset + BIG // 2


def _after_big(blob: bytes) -> int:
    """The header right after the BIG texture - a split there starts the last part on an entry."""
    with zipfile.ZipFile(io.BytesIO(blob)) as bundle:
        ordered = sorted(bundle.infolist(), key=lambda info: info.header_offset)
    big = next(n for n, info in enumerate(ordered) if info.compress_size == BIG)
    return ordered[big + 1].header_offset


class _Release:
    """Canned release assets served by ranges; Amaze's `hosted` files are counted apart."""

    def __init__(self, objects, hosted=None):
        self.objects, self.calls = dict(objects), []
        self.hosted, self.hosted_calls = dict(hosted or {}), []
        self.answer = {"tag_name": "v9", "assets": [
            {"name": name, "size": len(data), "browser_download_url": BASE + name}
            for name, data in sorted(self.objects.items())]}

    def serve(self, url, headers=None):
        name = url.rsplit("/", 1)[-1]
        spec = str((headers or {}).get("Range") or "")
        if name in self.objects:
            self.calls.append((name, spec))
            return _ranged_server(self.objects[name])(url, headers)
        self.hosted_calls.append((name, spec))
        if name not in self.hosted:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        blob = self.hosted[name]
        if spec == "bytes=0-0":    # GitHub's answer to one byte carries the whole size
            return _Served(blob[:1], {"Content-Range": "bytes 0-0/%d" % len(blob)})
        return _ranged_server(blob)(url, headers)

    def patched(self, testcase):
        from amaze.core import matx_sources
        for target, value in (("_request", self.serve),
                              ("get_json", lambda _url: self.answer)):
            patcher = mock.patch.object(matx_sources, target, value)
            patcher.start()
            testcase.addCleanup(patcher.stop)


def _stone_parts():
    blob = _archive("Stone", ["Volga_Blue", "Ardesia_Grigia_Polished"])
    return blob, _split(blob, _inside_big(blob, "Stone"))


def _release(testcase, skin_drop=(), hosted=None):
    _blob, (stone_z01, stone_zip) = _stone_parts()
    release = _Release({
        "Skin.zip": _archive("Skin", ["Skin_Dark"], drop=skin_drop),
        "Stone.z01": stone_z01, "Stone.zip": stone_zip,
        "Glass.zip": _archive("Glass", ["Glass_Clear"]),
        "README.txt": b"not an archive"}, hosted)
    release.patched(testcase)
    return release


def _previews(pictures) -> bytes:
    """Amaze's hosted previews zip: each picture stored as `<Category>/<Name>.jpg`."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as bundle:
        for member, data in pictures.items():
            bundle.writestr(member, data)
        bundle.writestr("previews.json", b"{}")
    return out.getvalue()


class SimReadyListingTest(unittest.TestCase):
    """Every .usda in every category archive is one tile, read off the directories alone."""

    def test_every_material_is_one_record(self):
        from amaze.core import matx_sources
        _release(self)
        records = matx_sources.SimReadySource().list_materials(limit=100)
        self.assertEqual(
            ["Glass/Glass_Clear", "Skin/Skin_Dark", "Stone/Ardesia_Grigia_Polished",
             "Stone/Volga_Blue"], sorted(r.uid for r in records))
        volga = next(r for r in records if r.uid == "Stone/Volga_Blue")
        self.assertEqual(("Volga Blue", "Stone", "package", "SimReady"),
                         (volga.title, volga.category, volga.kind, volga.source))
        self.assertEqual("MIT-0 (MIT No Attribution)", volga.licence,
                         "the licence must be the release's own words")
        self.assertEqual([BASE + "Stone.z01", BASE + "Stone.zip"],
                         [url for url, _size in volga.payload["parts"]],
                         "a split archive's parts must run .z01 first, the .zip last")
        self.assertEqual("Materials/Stone/Volga_Blue.usda", volga.payload["member"])

    def test_a_listing_reads_two_ranges_an_archive_and_a_relisting_none(self):
        """None counted from the end: GitHub's release host answers 501. ▸r/simready-release"""
        from amaze.core import matx_sources
        release = _release(self)
        source = matx_sources.SimReadySource()
        source.list_materials(limit=100)
        self.assertTrue(release.calls, "premise: the listing read nothing")
        self.assertEqual([], [c for c in release.calls if c[1].startswith("bytes=-")])
        self.assertLessEqual(len(release.calls), 2 * 3,
                             "the tail and the directory, per archive: %s" % release.calls)
        release.calls.clear()
        source.list_materials(limit=100)
        self.assertEqual([], release.calls, "the directories were not kept")
        source.refresh()
        source.list_materials(limit=100)
        self.assertTrue(release.calls, "Refresh left the directories cached")

    def test_a_directory_past_the_tail_block_is_read_in_one_request(self):
        """Metal's directory is 497 KB; a directory that outgrows the tail costs one more GET."""
        from amaze.core import matx_sources
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as bundle:
            bundle.writestr("Materials/Big/Glass_Clear.usda",
                            _read("Materials", "Glass", "Glass_Clear.usda"))
            for n in range(900):
                bundle.writestr("Materials/Big/textures/padding_%04d_%s.jpg" % (n, "x" * 40), b"")
        blob = out.getvalue()
        end = blob.rfind(b"PK\x05\x06")
        self.assertGreater(struct.unpack("<I", blob[end + 12:end + 16])[0],
                           matx_sources.RANGED_BLOCK, "premise: the directory outgrows the tail")
        release = _Release({"Big.zip": blob})
        release.patched(self)
        records = matx_sources.SimReadySource().list_materials(limit=100)
        self.assertEqual(["Big/Glass_Clear"], [r.uid for r in records])
        self.assertEqual(2, len(release.calls),
                         "the tail, then the whole directory: %s" % release.calls)

    def test_an_unreadable_archive_fails_the_listing_instead_of_shortening_it(self):
        from amaze.core import matx_sources
        release = _release(self)
        whole = release.objects["Glass.zip"]
        half = len(whole) // 2
        release.objects["Glass.zip"] = whole[:half] + bytes(len(whole) - half)
        source = matx_sources.SimReadySource()
        with self.assertRaises(RuntimeError):
            source.list_materials(limit=100)
        release.objects["Glass.zip"] = whole
        release.calls.clear()
        self.assertEqual(4, len(source.list_materials(limit=100)))
        self.assertEqual({"Glass.zip"}, {name for name, _r in release.calls},
                         "the archives that did read were read again")


class SimReadyRemembersTest(unittest.TestCase):
    """A session's first refresh re-reads only the archives the release changed."""

    def _listed(self):
        from amaze.core import matx_sources
        return matx_sources.SimReadySource().list_materials(limit=100)

    def test_a_new_session_reads_no_archive_its_last_listing_read(self):
        from amaze.core import matx_sources
        release = _release(self)
        before = self._listed()
        release.calls.clear()
        source = matx_sources.SimReadySource()    # the next Houdini session
        source.remember(before)
        after = source.list_materials(limit=100)
        self.assertEqual([], release.calls, "an unchanged archive was read again")
        self.assertEqual([r.to_dict() for r in before], [r.to_dict() for r in after])

    def test_an_archive_whose_size_changed_is_read_again(self):
        from amaze.core import matx_sources
        release = _release(self)
        before = self._listed()
        member = next(iter(_textures("Skin", "Skin_Dark")))
        release.objects["Skin.zip"] = _archive("Skin", ["Skin_Dark"], drop=(member,))
        release.answer = _Release(release.objects).answer    # same url, new size
        release.calls.clear()
        source = matx_sources.SimReadySource()
        source.remember(before)
        after = source.list_materials(limit=100)
        self.assertEqual({"Skin.zip"}, {name for name, _range in release.calls})
        self.assertEqual(sorted(r.uid for r in before), sorted(r.uid for r in after))

    def test_the_refresh_menu_reuses_nothing(self):
        """Refresh is the user asking to look, so the worker is handed no last listing."""
        from amaze.core import matx_library
        handed = []
        model = matx_library.MatxOnlineLibrary()
        self.addCleanup(model.shutdown)
        listed = self._listed_offline()
        model._load_cache = lambda: list(listed)    # the session's first open reads the disk

        class Worker(QtCore.QObject):
            done = QtCore.Signal(object, object, int)
            progressed = QtCore.Signal(int, int, int)
            finished = QtCore.Signal()

            def __init__(self, _sources, _generation, previous=()):
                super().__init__()
                handed.append(list(previous))

            def start(self):
                self.finished.emit()

        with mock.patch.object(matx_library, "_CatalogueWorker", Worker):
            model.reload()
            model.reload(force=True)
        self.assertEqual([len(listed), 0], [len(h) for h in handed],
                         "the first open hands its disk listing on, Refresh hands none")

    def _listed_offline(self):
        _release(self)
        return self._listed()


class SplitArchiveTest(unittest.TestCase):
    """`.z01` + `.zip` read as one zip, a member across the split included. ▸r/simready-release"""

    def test_every_member_reads_back_whole_wherever_the_split_lands(self):
        """At a boundary: 3.12+ zipfile checks entry ends against offsets taken before aiming."""
        from amaze.core import matx_sources
        blob = _archive("Stone", ["Volga_Blue", "Ardesia_Grigia_Polished"])
        for where, at in (("inside a member", _inside_big(blob, "Stone")),
                          ("at a member boundary", _after_big(blob))):
            with self.subTest(where):
                first, last = _split(blob, at)
                _Release({"Stone.z01": first, "Stone.zip": last}).patched(self)
                bundle, remote = matx_sources.open_remote_zip(
                    [(BASE + "Stone.z01", len(first)), (BASE + "Stone.zip", len(last))])
                with zipfile.ZipFile(io.BytesIO(blob)) as original:
                    for name in [n for n in original.namelist() if not n.endswith("/")]:
                        self.assertEqual(original.read(name),
                                         matx_sources.read_member(bundle, remote, name),
                                         "%s did not survive the split" % name)

    def test_a_directory_outside_the_last_part_is_refused(self):
        from amaze.core import matx_sources
        _blob, (first, last) = _stone_parts()
        record = last.rfind(b"PK\x05\x06")
        bent = bytearray(last)
        struct.pack_into("<H", bent, record + 6, 0)
        release = _Release({"Stone.z01": first, "Stone.zip": bytes(bent)})
        release.patched(self)
        with self.assertRaises(zipfile.BadZipFile):
            matx_sources.open_remote_zip(
                [(BASE + "Stone.z01", len(first)), (BASE + "Stone.zip", len(bent))])


class SimReadyFetchTest(unittest.TestCase):
    """One material's members alone, laid out as released, with its .mtlx beside its .usda."""

    def _fetch(self, uid, skin_drop=()):
        from amaze.core import matx_sources
        release = _release(self, skin_drop)
        source = matx_sources.SimReadySource()
        record = next(r for r in source.list_materials(limit=100) if r.uid == uid)
        dest = tempfile.mkdtemp(prefix="amaze_simready_fetch_")
        self.addCleanup(shutil.rmtree, dest, True)
        seen = []
        try:
            got = source.fetch(record, "original", dest, progress=seen.append)
        except Exception as exc:                             # noqa: BLE001
            self.fail("the fetch itself failed, so the import would too: %r" % exc)
        return record, dest, got, seen, release

    def _files(self, dest):
        return sorted(os.path.relpath(os.path.join(root, f), dest).replace(os.sep, "/")
                      for root, _dirs, files in os.walk(dest) for f in files)

    def test_the_package_lands_as_released_and_progress_runs_forward(self):
        _record, dest, got, seen, _release_ = self._fetch("Stone/Volga_Blue")
        self.assertEqual(
            ["Materials/Stone/Volga_Blue.mtlx", "Materials/Stone/Volga_Blue.usda",
             "Materials/Stone/textures/Volga_Blue_diffuse.jpg",
             "Materials/Stone/textures/Volga_Blue_glossy_roughness.jpg",
             "Materials/Stone/textures/Volga_Blue_normal.jpg",
             "open_pbr_uber_base_class.usda"], self._files(dest))
        self.assertEqual(os.path.join(dest, "Materials", "Stone", "Volga_Blue.mtlx"),
                         got["mtlx"])
        self.assertGreater(len(seen), 2, "premise: the big texture streams in chunks")
        self.assertEqual(sorted(seen), seen, "the bar stepped backwards")
        self.assertEqual(1.0, seen[-1])

    def test_a_span_longer_than_its_member_never_runs_the_bar_past_it(self):
        """A fetch reads whole blocks, so a member's request runs past the member itself."""
        from amaze.core import matx_sources
        shares = [matx_sources.member_share(100, 50, read, 80) for read in range(0, 81, 8)]
        self.assertEqual(sorted(shares), shares, "the share stepped backwards")
        self.assertEqual(150, shares[-1], "the last byte must land on the members done")
        self.assertLessEqual(max(shares), 150, "the bar ran into the next member's share")

    def test_each_texture_is_one_request_and_the_labels_become_tags(self):
        record, _dest, _got, _seen, release = self._fetch("Skin/Skin_Dark")
        skin = [c for c in release.calls if c[0] == "Skin.zip"]
        self.assertLessEqual(len(skin), 2 + 2 + 3,
                             "tail, directory, two documents and three textures: %s" % skin)
        self.assertEqual(["skin", "human", "body", "organic", "character", "dark"],
                         record.tags)

    def test_a_texture_the_archive_lacks_is_left_to_the_repair(self):
        from amaze.core import matx_sources
        missing = "Materials/Skin/textures/Skin_Dark_normal.jpg"
        _record, dest, got, _seen, _release_ = self._fetch("Skin/Skin_Dark", (missing,))
        self.assertNotIn(missing, self._files(dest))
        unresolved = [r["reference"] for r in matx_sources.repair_mtlx_references(
            got["mtlx"], dest) if not r["fixed_to"]]    # the package root, as the import passes it
        self.assertEqual(["textures/Skin_Dark_normal.jpg"], unresolved,
                         "the import's repair is what reports a texture never fetched")

    def test_a_texture_path_out_of_the_package_is_refused(self):
        from amaze.core import matx_sources
        text = _read("Materials", "Skin", "Skin_Dark.usda").decode("utf-8")
        hostile = text.replace("textures/Skin_Dark_normal.jpg", "../../../../escape.jpg")
        self.assertNotEqual(text, hostile, "premise: the reference was rewritten")
        release = _Release({"Skin.zip": _archive("Skin", ["Skin_Dark"])})
        out = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(release.objects["Skin.zip"])) as src, \
                zipfile.ZipFile(out, "w") as dst:
            for info in src.infolist():
                data = src.read(info)
                if info.filename.endswith("Skin_Dark.usda"):
                    data = hostile.encode("utf-8")
                dst.writestr(info, data)
        release = _Release({"Skin.zip": out.getvalue()})
        release.patched(self)
        source = matx_sources.SimReadySource()
        record = source.list_materials(limit=10)[0]
        dest = tempfile.mkdtemp(prefix="amaze_simready_fetch_")
        self.addCleanup(shutil.rmtree, dest, True)
        with test_support.captured_log() as log:
            try:
                source.fetch(record, "original", os.path.join(dest, "pkg"))
            except Exception as exc:                         # noqa: BLE001
                self.fail("a hostile path must cost that texture, not the import: %r" % exc)
        landing = os.path.join(os.path.dirname(dest), "escape.jpg")    # where ../../ from pkg points
        self.assertFalse(os.path.exists(landing), "a texture was written out of the package")
        said = [r for r in log.records("online") if "outside the library" in r.get("msg", "")]
        self.assertEqual(1, len(said), "the refused path was not logged once")


class NestedDocumentRepairTest(unittest.TestCase):
    """A .mtlx's references are relative to its own folder, as the translator reads them."""

    def _package(self, texture, reference):
        package = tempfile.mkdtemp(prefix="amaze_simready_repair_")
        self.addCleanup(shutil.rmtree, package, True)
        folder = os.path.join(package, "Materials", "Skin")
        os.makedirs(os.path.join(folder, "textures"))
        with open(os.path.join(folder, "textures", texture), "wb") as handle:
            handle.write(b"\xff\xd8 not decoded")
        document = os.path.join(folder, "Skin.mtlx")
        with open(document, "w", encoding="utf-8") as handle:
            handle.write('<materialx><tiledimage name="t" type="color3">'
                         '<input name="file" type="filename" value="%s"/>'
                         '</tiledimage></materialx>' % reference)
        return package, document

    def _value(self, document):
        with open(document, encoding="utf-8") as handle:
            return re.search(r'value="([^"]+)"', handle.read()).group(1)

    def test_a_working_reference_is_left_alone_and_a_repair_is_relative(self):
        from amaze.core import matx_sources
        package, document = self._package("a.jpg", "textures/a.jpg")
        self.assertEqual([], matx_sources.repair_mtlx_references(document, package))
        self.assertEqual("textures/a.jpg", self._value(document))
        package, document = self._package("a.png", "textures/a.jpg")
        matx_sources.repair_mtlx_references(document, package)
        self.assertEqual("textures/a.png", self._value(document),
                         "repaired relative to the package, not to the document")


class SimReadyImportTest(unittest.TestCase):
    """Through the app's own import door: every texture the material reads is on disk."""

    def test_every_image_points_at_a_downloaded_file(self):
        from amaze.core import matx_import, matx_sources
        if hou.getenv("OCIO") is None:
            hou.putenv("OCIO", "/dev/null")
        prefs = test_support.fixture_prefs(self)
        prefs.render_on_import = 0
        _release(self)
        source = matx_sources.SimReadySource()
        record = next(r for r in source.list_materials(limit=100)
                      if r.uid == "Stone/Volga_Blue")
        destination = hou.node("/mat") or hou.node("/").createNode("mat")
        builder, why = matx_import.build_in_scene(record, source, "original",
                                                  destination, prefs)
        self.assertIsNotNone(builder, why)
        self.addCleanup(builder.destroy)
        files = [node.parm("file").eval() for node in builder.children()
                 if node.type().name().startswith("mtlxtiledimage")]
        self.assertEqual(3, len(files), "premise: Volga Blue reads three maps")
        self.assertEqual([], [f for f in files if not os.path.isfile(f)],
                         "an image points at a file that is not there - it renders black")


class MaterialSpecTest(unittest.TestCase):
    """The composed USD graph read into constants, maps and normal maps. ▸r/simready-graph"""

    def _spec(self, category, name):
        from amaze.core import matx_usd
        return matx_usd.material_spec(os.path.join(FIXTURES, "Materials", category,
                                                   name + ".usda"))

    def _document(self, spec):
        import MaterialX as mx
        from amaze.core import matx_usd
        folder = tempfile.mkdtemp(prefix="amaze_simready_mtlx_")
        self.addCleanup(shutil.rmtree, folder, True)
        path = matx_usd.write_mtlx(spec, os.path.join(folder, "m.mtlx"))
        doc = mx.createDocument()
        mx.readFromXmlFile(doc, path)
        return doc

    def test_a_raw_colour_map_reads_as_data_then_converts(self):
        spec = self._spec("Skin", "Skin_Dark")
        image = spec["images"]["specular_color"]
        self.assertEqual(("raw", "color3", (5.0, 5.0)),
                         (image["colorspace"].lower(), image["type"], image["tiling"]))
        doc = self._document(spec)
        read = doc.getNode("tiledimage_specular_color")
        convert = doc.getNode("convert_specular_color")
        self.assertIsNotNone(convert, "a raw colour map was read as colour, with no convert")
        self.assertEqual(("vector3", "color3"), (read.getType(), convert.getType()))
        self.assertEqual("tiledimage_specular_color", convert.getInput("in").getNodeName())
        self.assertEqual("convert_specular_color", doc.getNode(
            "open_pbr_surface").getInput("specular_color").getNodeName())

    def test_a_flipped_normal_map_flips_only_its_green_and_an_srgb_map_says_so(self):
        spec = self._spec("Stone", "Volga_Blue")
        self.assertEqual((False, True, False), spec["normals"]["geometry_normal"]["flip"])
        doc = self._document(spec)
        self.assertEqual("1, -1, 1", doc.getNode("flip_geometry_normal")
                         .getInput("in2").getValueString())
        self.assertEqual("0, 1, 0", doc.getNode("unflip_geometry_normal")
                         .getInput("in2").getValueString())
        self.assertEqual("srgb_texture", doc.getNode("tiledimage_base_color")
                         .getInput("file").getAttribute("colorspace"))
        self.assertEqual("", doc.getNode("tiledimage_specular_roughness")
                         .getInput("file").getAttribute("colorspace"),
                         "a data map carries no colour space; the translator reads it Raw")

    def test_a_coat_normal_map_lands_on_the_coat(self):
        normals = self._spec("Stone", "Volga_Blue_Deep_Pollished")["normals"]
        self.assertIn("geometry_coat_normal", normals)
        self.assertTrue(normals["geometry_coat_normal"]["flip"][1])

    def test_a_values_only_glass_is_its_constants(self):
        spec = self._spec("Glass", "Glass_Clear")
        self.assertEqual(({}, {}, []), (spec["images"], spec["normals"], spec["unread"]))
        self.assertEqual(("float", 1.0), spec["constants"]["transmission_weight"])
        self.assertAlmostEqual(1.47, spec["constants"]["specular_ior"][1], places=5)

    def test_an_input_nothing_reads_is_left_out(self):
        spec = self._spec("Stone", "Ardesia_Grigia_Polished")
        self.assertEqual([], spec["unread"])
        self.assertNotIn("specular_roughness_", spec["constants"])

    def test_a_dot_slash_texture_path_is_kept_as_written(self):
        from amaze.core import matx_usd
        self.assertEqual(["./textures/Plastic_Ivory_White_normal.jpg"],
                         matx_usd.texture_files(self._spec("Plastic", "Plastic_Ivory_White")))

    def test_a_colour_map_with_no_colour_space_stays_colour(self):
        """Only raw and linear spaces read as data; auto leaves an 8-bit map to Karma's sRGB."""
        spec = {"name": "M", "labels": [], "constants": {}, "normals": {}, "unread": [],
                "images": {"base_color": {"file": "textures/t.jpg", "colorspace": "",
                                          "type": "color3", "tiling": (1.0, 1.0),
                                          "offset": (0.0, 0.0)}}}
        doc = self._document(spec)
        self.assertEqual("color3", doc.getNode("tiledimage_base_color").getType())
        self.assertIsNone(doc.getNode("convert_base_color"))

    def test_a_value_too_small_for_a_float_is_written_as_zero(self):
        """Five released Plastics write `3e-45`, which MaterialX refuses. ▸r/simready-graph"""
        spec = {"name": "M", "labels": [], "images": {}, "normals": {}, "unread": [],
                "constants": {"transmission_color": ("color3", (0.0, 3e-45, 0.0)),
                              "transmission_weight": ("float", 1e-40)}}
        surface = self._document(spec).getNode("open_pbr_surface")
        self.assertEqual("0, 0, 0", surface.getInput("transmission_color").getValueString())
        self.assertEqual("0", surface.getInput("transmission_weight").getValueString())

    def test_an_unwired_graph_is_reported_not_raised(self):
        from amaze.core import matx_usd
        folder = tempfile.mkdtemp(prefix="amaze_simready_unwired_")
        self.addCleanup(shutil.rmtree, folder, True)
        shutil.copytree(os.path.join(FIXTURES, "Materials"), os.path.join(folder, "Materials"))
        base = _read("open_pbr_uber_base_class.usda").decode("utf-8")
        wire = ("float3 inputs:in.connect = "
                "</open_pbr_uber_base/tiledimage_geometry_normal.outputs:out>")
        self.assertIn(wire, base, "premise: the base class wires the normal image")
        with open(os.path.join(folder, "open_pbr_uber_base_class.usda"), "w",
                  encoding="utf-8") as handle:
            handle.write(base.replace(wire, ""))
        try:
            spec = matx_usd.material_spec(os.path.join(
                folder, "Materials", "Stone", "Ardesia_Grigia_Polished.usda"))
        except Exception as exc:                             # noqa: BLE001
            self.fail("an unknown graph failed the whole import: %r" % exc)
        self.assertNotIn("geometry_normal", spec["normals"])
        self.assertTrue(any("not wired" in why for why in spec["unread"]), spec["unread"])

    def test_every_fixture_writes_a_valid_document(self):
        for category, name in (("Skin", "Skin_Dark"), ("Stone", "Volga_Blue"),
                               ("Stone", "Volga_Blue_Deep_Pollished"),
                               ("Stone", "Ardesia_Grigia_Polished"),
                               ("Glass", "Glass_Clear"), ("Plastic", "Plastic_Ivory_White")):
            with self.subTest(name=name):
                self.assertTrue(self._document(self._spec(category, name)).validate()[0])


class TranslatedVopsTest(unittest.TestCase):
    """The document through the app's material door: the nodes a hand-built OpenPBR has."""

    def _built(self, category, name):
        from amaze.core import matx_translate, matx_usd
        from amaze.render import nodes
        folder = tempfile.mkdtemp(prefix="amaze_simready_vops_")
        self.addCleanup(shutil.rmtree, folder, True)
        path = matx_usd.write_mtlx(matx_usd.material_spec(os.path.join(
            FIXTURES, "Materials", category, name + ".usda")),
            os.path.join(folder, name + ".mtlx"))
        parent = hou.node("/obj").createNode("matnet")
        self.addCleanup(parent.destroy)
        built = nodes.build_karma_material(
            parent, name, lambda b: matx_translate.build_material(path, b, name))
        self.assertTrue(built.wired, "the surface is not wired to the output")
        return {child.name(): child for child in built.builder.children()}

    def test_a_raw_colour_map_reaches_the_shader_as_colour(self):
        vops = self._built("Skin", "Skin_Dark")
        self.assertIn("convert_specular_color", vops, "the raw colour map was not converted")
        convert = vops["convert_specular_color"]
        self.assertEqual("vector3color3", convert.parm("signature").eval())
        self.assertEqual(["color"], list(convert.outputDataTypes()))
        surface = vops["open_pbr_surface"]
        fed = surface.input(surface.inputNames().index("specular_color"))
        self.assertEqual(convert.path(), fed.path() if fed else None)

    def test_the_green_flip_is_built_on_an_openpbr_surface(self):
        vops = self._built("Stone", "Volga_Blue")
        self.assertEqual((1.0, -1.0, 1.0),
                         tuple(vops["flip_geometry_normal"].parmTuple("in2_vector3").eval()))
        self.assertEqual("srgb_texture",
                         vops["tiledimage_base_color"].parm("filecolorspace").eval())
        types = {vop.type().name().split("::")[0] for vop in vops.values()}
        self.assertIn("mtlxopen_pbr_surface", types)
        self.assertNotIn("mtlxstandard_surface", types)


class TranslatorSignatureTest(unittest.TestCase):
    """A `convert` VOP's signature is its input type then its own. ▸r/simready-graph"""

    def test_convert_names_its_input_type_then_its_own(self):
        import MaterialX as mx
        from amaze.core import matx_translate
        doc = mx.createDocument()
        image = doc.addNode("tiledimage", "image", "vector3")
        convert = doc.addNode("convert", "convert", "color3")
        convert.setConnectedNode("in", image)
        self.assertEqual("vector3color3", matx_translate._signature(convert))
        self.assertEqual("vector3", matx_translate._signature(image))


class PreviewlessTileTest(unittest.TestCase):
    """A source that ships no picture shows the Material section's own face. ▸r/tile-faces"""

    def test_a_package_tile_with_no_preview_shows_the_material_face(self):
        from amaze.core import library, matx_library, matx_sources, thumbnails, tile_icons
        record = matx_sources.MatxRecord(source="SimReady", uid="Skin/Skin_Dark",
                                         title="Skin Dark", category="Skin", kind="package")
        model = matx_library.MatxOnlineLibrary(
            preferences=type("P", (), {"rendersize": 64})())
        key = model._preview_key(record)
        thumbnails.engine.discard(key)
        model._queue_previews([record])
        image = thumbnails.engine.peek(key)
        self.assertIsNotNone(image, "a tile with no preview stayed blank")
        self.assertEqual(tile_icons.generic_image(library.MaterialLibrary.TILE_FACE), image,
                         "the online face differs from the Material section's")


class SimReadyPreviewsTest(unittest.TestCase):
    """A tile's picture from Amaze's hosted zip: placed at listing, one ranged read each."""

    PICTURE = bytes(range(256)) * 40

    def _listed(self, hosted):
        from amaze.core import matx_sources
        release = _release(self, hosted=hosted)
        return release, matx_sources.SimReadySource().list_materials(limit=100)

    def test_a_material_with_a_hosted_picture_is_listed_with_its_place(self):
        _release_, records = self._listed({"simready-previews.zip": _previews(
            {"Skin/Skin_Dark.jpg": self.PICTURE})})
        by_uid = {r.uid: r for r in records}
        place = by_uid["Skin/Skin_Dark"].payload.get("preview") or {}
        self.assertEqual(zlib.crc32(self.PICTURE), place.get("crc"))
        self.assertNotIn("preview", by_uid["Glass/Glass_Clear"].payload)

    def test_previews_out_of_reach_leave_the_listing_whole(self):
        release, records = self._listed({})
        self.assertTrue(release.hosted_calls, "premise: the previews were asked for")
        self.assertEqual(4, len(records))
        self.assertFalse([r.uid for r in records if "preview" in r.payload])

    def test_a_picture_is_one_ranged_read_and_its_crc_is_checked(self):
        from amaze.core import matx_sources
        release, records = self._listed({"simready-previews.zip": _previews(
            {"Skin/Skin_Dark.jpg": self.PICTURE})})
        skin = next(r for r in records if r.uid == "Skin/Skin_Dark")
        folder = tempfile.mkdtemp(prefix="amaze_simready_preview_")
        self.addCleanup(shutil.rmtree, folder, True)
        release.hosted_calls.clear()
        matx_sources.SimReadySource().read_thumb_to(skin, os.path.join(folder, "skin.png"))
        with open(os.path.join(folder, "skin.png"), "rb") as handle:
            self.assertEqual(self.PICTURE, handle.read())
        self.assertEqual(1, len(release.hosted_calls), release.hosted_calls)
        skin.payload["preview"]["crc"] ^= 1
        with self.assertRaises(ValueError):
            matx_sources.SimReadySource().read_thumb_to(skin, os.path.join(folder, "old.png"))


class PhysicallyBasedPreviewsTest(unittest.TestCase):
    """PhysicallyBased's tiles carry their hosted pictures, found by the material's name."""

    def test_a_material_with_a_hosted_picture_is_listed_with_its_place(self):
        from amaze.core import matx_sources
        picture = bytes(range(256)) * 10
        hosted = _previews({"Aluminum.jpg": picture})

        def serve(url, headers=None):
            if str((headers or {}).get("Range") or "") == "bytes=0-0":
                return _Served(hosted[:1], {"Content-Range": "bytes 0-0/%d" % len(hosted)})
            return _ranged_server(hosted)(url, headers)

        def offline(_url):
            raise urllib.error.URLError("offline")

        for target, value in (("_request", serve), ("get_json", offline)):
            patcher = mock.patch.object(matx_sources, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        records = {r.uid: r for r in
                   matx_sources.PhysicallyBasedSource().list_materials(limit=1000)}
        place = records["Aluminum"].payload.get("preview") or {}
        self.assertEqual(zlib.crc32(picture), place.get("crc"))
        self.assertNotIn("preview", records["Banana"].payload)


class RGLPreviewsTest(unittest.TestCase):
    """RGL's tiles carry their hosted pictures, found by the measurement's name."""

    def test_a_material_with_a_hosted_picture_is_listed_with_its_place(self):
        from amaze.core import matx_sources
        picture = bytes(range(256)) * 12
        hosted = _previews({"acrylic_felt_green.jpg": picture})

        def serve(url, headers=None):
            if str((headers or {}).get("Range") or "") == "bytes=0-0":
                return _Served(hosted[:1], {"Content-Range": "bytes 0-0/%d" % len(hosted)})
            return _ranged_server(hosted)(url, headers)

        def offline(_url):
            raise urllib.error.URLError("offline")

        for target, value in (("_request", serve), ("get_text", offline)):
            patcher = mock.patch.object(matx_sources, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        records = {r.uid: r for r in matx_sources.RGLSource().list_materials(limit=1000)}
        place = records["acrylic_felt_green"].payload.get("preview") or {}
        self.assertEqual(zlib.crc32(picture), place.get("crc"))
        self.assertNotIn("preview", records["acrylic_felt_orange"].payload)


class PolyHavenPreviewsTest(unittest.TestCase):
    """PolyHaven's tiles carry Amaze's hosted pictures, which outrank PolyHaven's own."""

    def test_a_material_with_a_hosted_picture_is_listed_with_its_place(self):
        from amaze.core import matx_sources
        picture = bytes(range(256)) * 14
        hosted = _previews({"brick_4.jpg": picture})

        def serve(url, headers=None):
            if str((headers or {}).get("Range") or "") == "bytes=0-0":
                return _Served(hosted[:1], {"Content-Range": "bytes 0-0/%d" % len(hosted)})
            return _ranged_server(hosted)(url, headers)

        assets = {"brick_4": {"name": "Brick 4", "thumbnail_url": "https://cdn/brick_4.png"},
                  "moon_02": {"name": "Moon 02", "thumbnail_url": "https://cdn/moon_02.png"}}
        for target, value in (("_request", serve), ("get_json", lambda _url: assets)):
            patcher = mock.patch.object(matx_sources, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        records = {r.uid: r for r in matx_sources.PolyHavenSource().list_materials(limit=100)}
        place = records["brick_4"].payload.get("preview") or {}
        self.assertEqual(zlib.crc32(picture), place.get("crc"))
        self.assertNotIn("preview", records["moon_02"].payload)


class GPUOpenPreviewsTest(unittest.TestCase):
    """GPUOpen's tiles carry Amaze's hosted pictures, found by the material's id."""

    def test_a_material_with_a_hosted_picture_is_listed_with_its_place(self):
        from amaze.core import matx_sources
        picture = bytes(range(256)) * 16
        hosted = _previews({"m-brick.jpg": picture})

        def serve(url, headers=None):
            if str((headers or {}).get("Range") or "") == "bytes=0-0":
                return _Served(hosted[:1], {"Content-Range": "bytes 0-0/%d" % len(hosted)})
            return _ranged_server(hosted)(url, headers)

        def answer(url):
            if "/categories/" in url:
                return {"results": []}
            return {"results": [{"id": "m-brick", "title": "Brick", "renders": ["r1"]},
                                {"id": "m-moss", "title": "Moss", "renders": ["r2"]}]}

        for target, value in (("_request", serve), ("get_json", answer)):
            patcher = mock.patch.object(matx_sources, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        records = {r.uid: r for r in matx_sources.GPUOpenSource().list_materials(limit=100)}
        place = records["m-brick"].payload.get("preview") or {}
        self.assertEqual(zlib.crc32(picture), place.get("crc"))
        self.assertNotIn("preview", records["m-moss"].payload)


class ListingProgressTest(unittest.TestCase):
    """The online listing puts a step per source on the thin bar, from opening to the pictures."""

    def test_the_worker_reports_each_source_it_has_listed(self):
        from amaze.core import matx_library

        class Source:
            def __init__(self, name):
                self.name = name

            def remember(self, records):
                pass

            def list_materials(self, limit=60):
                return []

        worker = matx_library._CatalogueWorker([Source("A"), Source("B")], 4)
        steps = []
        worker.progressed.connect(lambda *step: steps.append(step))
        worker.run()
        self.assertEqual([(0, 2, 4), (1, 2, 4), (2, 2, 4)], steps)

    def test_the_bar_shows_the_current_listing_unless_pictures_hold_it(self):
        from amaze.core import matx_library
        model = matx_library.MatxOnlineLibrary()
        self.addCleanup(model.shutdown)
        shown = []
        model.progress_changed.connect(lambda done, total: shown.append((done, total)))
        model._on_catalogue_progress(1, 6, model._generation)
        model._on_catalogue_progress(2, 6, model._generation - 1)    # an older listing's step
        model._preview_total = 5
        model._on_catalogue_progress(3, 6, model._generation)
        self.assertEqual([(1, 6)], shown)


class HostedPreviewTileTest(unittest.TestCase):
    """A SimReady tile with a hosted picture reads it, and a re-render is a new picture."""

    def _model_and_record(self, crc):
        from amaze.core import matx_library, matx_sources
        model = matx_library.MatxOnlineLibrary(
            preferences=type("P", (), {"rendersize": 64})())
        return model, matx_sources.MatxRecord(
            source="SimReady", uid="Skin/Skin_Dark", title="Skin Dark", category="Skin",
            kind="package", payload={"preview": {"offset": 0, "size": 1, "crc": crc}})

    def _jobs(self, model, record) -> list:
        """The preview jobs `record` queues, the worker that would run them held back."""
        from amaze.core import matx_library
        made = []

        class Worker:
            def __init__(self, jobs):
                made.extend(jobs)
                self.ready = self.attempted = self.finished = mock.MagicMock()

            def start(self):
                pass

        with mock.patch.object(matx_library, "_PreviewWorker", Worker):
            model._queue_previews([record])
        return made

    def test_the_tile_reads_its_picture_and_its_crc_names_tile_and_cache(self):
        model, record = self._model_and_record(7)
        jobs = self._jobs(model, record)
        self.assertEqual(1, len(jobs), "no picture was asked for")
        (key, reader, path), = jobs
        self.assertTrue(callable(reader), "a hosted picture went to a URL download")
        self.assertEqual(model._preview_key(record), key)
        _model, rerendered = self._model_and_record(8)
        self.assertNotEqual(path, model._cache_path(rerendered),
                            "a re-rendered picture kept the old cache file")
        self.assertNotEqual(key, model._preview_key(rerendered),
                            "a re-rendered picture kept the old tile")

    def test_a_values_tile_reads_its_hosted_picture_instead_of_drawing(self):
        model, record = self._model_and_record(7)
        record.source, record.kind = "PhysicallyBased", "values"
        record.payload["values"] = {"color": [0.8, 0.2, 0.1]}
        jobs = self._jobs(model, record)
        self.assertEqual(1, len(jobs), "the tile was drawn from its numbers")
        self.assertTrue(callable(jobs[0][1]), "a hosted picture went to a URL download")

    def test_a_hosted_picture_outranks_the_sources_own(self):
        model, record = self._model_and_record(7)
        record.source, record.preview_url = "PolyHaven", "https://cdn.example/brick_4.png"
        jobs = self._jobs(model, record)
        self.assertEqual(1, len(jobs), jobs)
        self.assertTrue(callable(jobs[0][1]), "the source's own picture was fetched instead")

    def test_a_relisting_that_brings_pictures_redraws_the_tiles(self):
        model, pictured = self._model_and_record(7)
        _model, plain = self._model_and_record(7)
        plain.payload = {}
        model._all, model._records = [plain], [plain]
        with mock.patch.object(model, "_apply_filter") as redraw, \
                mock.patch.object(model, "_save_cache"):
            model._on_catalogue([pictured], [], model._generation)
        redraw.assert_called_once()


def _redshift_available():
    try:
        return hou.vopNodeTypeCategory().nodeType("redshift_vopnet") is not None
    except Exception:                                        # noqa: BLE001
        return False


@unittest.skipUnless(_redshift_available(), "the Redshift plugin is not loaded")
class RedshiftTiledImageTest(unittest.TestCase):
    """Tiling and a raw colour map cross to Redshift as Karma reads them. ▸r/rs-sampler-uv"""

    def _converted(self, produce):
        from amaze.render import nodes, redshift_converter
        parent = hou.node("/obj").createNode("matnet")
        self.addCleanup(parent.destroy)
        built = nodes.build_karma_material(parent, "karma_source", produce)
        rs_builder, shader, _wired, report = redshift_converter.convert_karma_builder(
            built.builder, parent, "rs_twin")
        samplers = [c for c in rs_builder.allSubChildren()
                    if c.type().name() == "redshift::TextureSampler"]
        return shader, samplers, report

    def test_tiling_and_offset_ride_the_sampler(self):
        def produce(builder):
            shader = builder.createNode("mtlxopen_pbr_surface")
            image = builder.createNode("mtlxtiledimage")
            image.parm("signature").set("color3")
            image.parm("file").set("$AMAZELIB/matX/t/textures/tiled.jpg")
            image.parmTuple("uvtiling").set((4.0, 2.0))
            image.parmTuple("uvoffset").set((0.4, 0.5))
            shader.setNamedInput("base_color", image, 0)
            return shader, None
        _shader, samplers, report = self._converted(produce)
        self.assertEqual(1, len(samplers), report.summary_lines())
        self.assertEqual((4.0, 2.0), tuple(samplers[0].parmTuple("scale").eval()))
        offset = tuple(round(v, 6) for v in samplers[0].parmTuple("offset").eval())
        self.assertEqual((-0.1, -0.25), offset, "offset is -uvoffset / scale")

    def test_both_openpbr_normal_maps_reach_redshift(self):
        """OpenPBR names its normals geometry_normal and geometry_coat_normal, not normal."""
        def produce(builder):
            shader = builder.createNode("mtlxopen_pbr_surface")
            for name in ("geometry_normal", "geometry_coat_normal"):
                image = builder.createNode("mtlxtiledimage")
                image.parm("signature").set("vector3")
                image.parm("file").set("$AMAZELIB/matX/t/textures/%s.jpg" % name)
                mapped = builder.createNode("mtlxnormalmap")
                mapped.setNamedInput("in", image, 0)
                shader.setNamedInput(name, mapped, 0)
            return shader, None
        shader, _samplers, report = self._converted(produce)
        self.assertEqual([], report.skipped, report.summary_lines())
        for name in ("geometry_normal", "geometry_coat_normal"):
            fed = shader.input(shader.inputNames().index(name))
            self.assertEqual("redshift::BumpMap", fed.type().name() if fed else None, name)

    def test_a_raw_colour_map_reads_raw_through_its_convert(self):
        def produce(builder):
            shader = builder.createNode("mtlxopen_pbr_surface")
            image = builder.createNode("mtlxtiledimage")
            image.parm("signature").set("vector3")
            image.parm("file").set("$AMAZELIB/matX/t/textures/weight.jpg")
            convert = builder.createNode("mtlxconvert")
            convert.parm("signature").set("vector3color3")
            convert.setNamedInput("in", image, 0)
            shader.setNamedInput("specular_color", convert, 0)
            return shader, None
        shader, samplers, report = self._converted(produce)
        self.assertEqual([], report.skipped, report.summary_lines())
        self.assertEqual(1, len(samplers))
        self.assertEqual("Raw", samplers[0].parm("tex0_colorSpace").evalAsString())
        fed = shader.input(shader.inputNames().index("specular_color"))
        self.assertEqual(samplers[0].path(), fed.path() if fed else None)


if __name__ == "__main__":
    unittest.main()
