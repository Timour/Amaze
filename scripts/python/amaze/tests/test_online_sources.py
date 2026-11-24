"""Online sources: one test per requirement in docs/requirements/online-sources.md."""

import io
import os
import re
import shutil
import ssl
import tempfile
import types
import unittest
import urllib.error
import zipfile
from unittest import mock

import hou

from amaze.core import debug, matx_import, matx_sources, matx_translate, notes, packages
from amaze.tests import test_support

SIMREADY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "simready")
URL = "https://example.invalid/v9/Stone.zip"
BIG = 300 * 1024    # a texture over several blocks, so its download reports progress


def _read(*parts) -> bytes:
    with open(os.path.join(SIMREADY, *parts), "rb") as handle:
        return handle.read()


def simready(testcase) -> tuple:
    """SimReady's Volga Blue served as its release serves it: (source, record, texture members)."""
    usda = _read("Materials", "Stone", "Volga_Blue.usda")
    textures = {os.path.normpath("Materials/Stone/" + ref).replace(os.sep, "/"): bytes(
        (n + i) % 251 for i in range(BIG if n == 0 else 4096)) for n, ref in enumerate(
        re.findall(r"_texture_file = @([^@]+)@", usda.decode("utf-8")))}
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("Materials/Stone/Volga_Blue.usda", usda)
        bundle.writestr("open_pbr_uber_base_class.usda", _read("open_pbr_uber_base_class.usda"))
        for member, data in textures.items():
            bundle.writestr(member, data)
    blob = archive.getvalue()
    test_support.serve(testcase, test_support.ranges_of(blob))
    record = matx_sources.MatxRecord(
        source="SimReady", uid="Stone/Volga_Blue", title="Volga Blue", kind="package",
        payload={"parts": [[URL, len(blob)]], "member": "Materials/Stone/Volga_Blue.usda"})
    return matx_sources.SimReadySource(), record, textures


class _Fetch:
    """A source whose fetch writes a document into the folder it is given, or fails as told."""

    def __init__(self, fail=None) -> None:
        self.fail, self.fetched = fail, []

    def fetch(self, record, resolution, dest, progress=None):
        self.fetched.append(resolution)
        test_support.put(dest, "m.mtlx", '<materialx version="1.38"/>')
        test_support.put(dest, "half.png", b"half a texture")
        if self.fail is not None:
            raise self.fail
        return {"mtlx": os.path.join(dest, "m.mtlx")}

    def page_url(self, record) -> str:
        return "https://example.invalid/" + record.uid


class OnlineSourceTest(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_online_")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def record(self, kind="package", **payload):
        return matx_sources.MatxRecord(source="Test", uid="brick", title="Brick", kind=kind,
                                       payload=payload)

    def test_on01_a_path_leading_outside_the_download_is_skipped_and_reported(self):
        dest = os.path.join(self.dir, "download", "brick")
        test_support.serve(self, lambda url, headers: b"file at " + url.encode())
        files = {"mtlx": {"1k": {"mtlx": {"url": "https://example.invalid/brick.mtlx", "include": {
            "textures/a.png": {"url": "https://example.invalid/a.png"},
            "../../escaped.png": {"url": "https://example.invalid/e.png"}}}}}}
        with mock.patch.object(debug, "alert") as alert:
            matx_sources.PolyHavenSource().fetch(self.record(_files=files), "1k", dest)
        self.assertEqual(["download"], os.listdir(self.dir), "a file was written outside it")
        self.assertTrue(os.path.isfile(os.path.join(dest, "textures", "a.png")))
        alert.assert_called_once()
        inside = test_support.put(dest, "wood.png", b"png")
        test_support.put(self.dir, "outside.png", b"png")
        for value, resolved in (("wood.png", inside), ("../../outside.png", ""),
                                (os.path.join(self.dir, "outside.png"), "")):
            self.assertEqual(os.path.normpath(resolved) if resolved else "",
                             matx_translate._resolve_file(value, dest, ""), value)

    def test_on02_a_download_arrives_whole_or_not_at_all(self):
        path = os.path.join(self.dir, "brick.zip")

        def esc(read, total):
            raise hou.OperationInterrupted()

        body = b"x" * 200000
        for name, reply, how in (
                ("short", test_support.Reply(body[:100], {"Content-Length": "200000"}), {}),
                ("over the cap", body, {"ceiling": 1000}),
                ("Esc", body, {"on_bytes": esc})):
            with self.subTest(name), self.assertRaises((OSError, hou.OperationInterrupted)):
                test_support.serve(self, lambda url, headers, reply=reply: reply)
                matx_sources.download("https://example.invalid/b.zip", path, **how)
            self.assertEqual([], os.listdir(self.dir), "a part of it stayed")
        dest = os.path.join(self.dir, "tex", "brick")
        for fail in (OSError("cut off"), hou.OperationInterrupted()):
            with self.subTest(type(fail).__name__):
                try:
                    produce, _note, error = matx_import._producer_for(
                        self.record(), _Fetch(fail), "1k", dest)
                except hou.OperationInterrupted:
                    produce, error = None, "stopped"
                self.assertTrue(error and produce is None)
                self.assertEqual([], os.listdir(os.path.dirname(dest)), "a folder stayed")

    def test_on10_only_https_and_only_a_verified_certificate(self):
        self.assertEqual("", matx_sources._checked_url("http://example.invalid/a.zip"))
        with self.assertRaises(urllib.error.URLError):
            matx_sources._request("http://example.invalid/a.zip")
        self.assertIsNone(matx_sources._HttpsOnlyRedirects().redirect_request(
            None, None, 302, "Found", {}, "http://example.invalid/a.zip"))
        context = matx_sources._ssl_context()
        self.assertEqual((ssl.CERT_REQUIRED, True), (context.verify_mode, context.check_hostname))
        opened = []

        def refuse(opener, request, timeout=None):
            opened.append(request)
            raise urllib.error.URLError(ssl.SSLCertVerificationError("not verified"))

        with mock.patch("urllib.request.OpenerDirector.open", refuse), \
                self.assertRaises(urllib.error.URLError):
            matx_sources._request("https://example.invalid/a.zip")
        self.assertEqual(1, len(opened), "a refused certificate was tried again")

    def test_on11_an_import_into_the_library_leaves_the_scene_as_it_was(self):
        source = types.SimpleNamespace(page_url=lambda record: "", fetch=lambda *a, **k: {
            "values": {"color": [0.5, 0.4, 0.3], "roughness": 0.4}})
        row = types.SimpleNamespace(license="", _extra={})
        library = types.SimpleNamespace(find_asset_row_by_id=lambda key: 0, assets=[row],
                                        save=lambda: True, NOTES_SECTION="material",
                                        rowCount=lambda: 1)

        def save(builder, *args, **how):
            builder.setUserData("assetlib_id", "new")
            return "Karma"

        scene = [node.path() for node in hou.node("/").allSubChildren()]
        undos = hou.undos.undoLabels()
        with mock.patch.object(notes, "set_note"):
            ok, why = matx_import.import_record(self.record("values"), source, None, library,
                                                None, save=save)
        self.assertTrue(ok, why)
        self.assertEqual(scene, [node.path() for node in hou.node("/").allSubChildren()])
        self.assertEqual(undos, hou.undos.undoLabels(), "the import left an undo step")

    def test_on12_an_import_shows_progress_stops_on_esc_and_reads_nothing_over_the_cap(self):
        source, record, textures = simready(self)
        steps = []
        source.fetch(record, None, os.path.join(self.dir, "whole"), progress=steps.append)
        self.assertGreater(len(steps), 2, "no progress was shown")
        self.assertEqual((sorted(steps), 1.0), (steps, steps[-1]))
        extracted = []
        real = matx_sources.extract_member
        with mock.patch.object(matx_sources, "extract_member", lambda bundle, remote, name, *a, **k: (
                extracted.append(name), real(bundle, remote, name, *a, **k))), \
                mock.patch.object(packages, "MAX_UNPACKED_BYTES", BIG), \
                self.assertRaises(matx_sources.DownloadTooLarge):
            source.fetch(record, None, os.path.join(self.dir, "capped"))
        self.assertEqual([], [name for name in extracted if name in textures])

        def esc(fraction):
            raise hou.OperationInterrupted()

        with self.assertRaises(hou.OperationInterrupted):
            source.fetch(record, None, os.path.join(self.dir, "stopped"), progress=esc)

    def test_on21_the_resolution_asked_for_or_the_nearest_is_fetched(self):
        offered = ["1k", "2k", "8k"]
        self.assertEqual("2k", matx_sources.pick_resolution(offered, "2k"))
        self.assertEqual("8k", matx_sources.pick_resolution(offered, "4k"))
        self.assertEqual("8k", matx_sources.pick_resolution(offered, "16k"))
        self.assertIsNone(matx_sources.pick_resolution([], "2k"))

    def test_on22_a_scene_download_is_reused_only_at_the_same_resolution(self):
        hip = test_support.hip_in_scratch(self)
        record, fetcher = self.record(), _Fetch()
        one, two = (matx_import._scene_download(record, res) for res in ("1k", "2k"))
        self.assertNotEqual(one, two)
        self.assertTrue(one.startswith(os.path.join(hip, matx_import.SCENE_DOWNLOADS)))
        for dest, resolution in ((one, "1k"), (one, "1k"), (two, "2k")):
            self.assertEqual("", matx_import._producer_for(record, fetcher, resolution, dest)[2])
        self.assertEqual(["1k", "2k"], fetcher.fetched, "a download was not reused, or was")
        with matx_import._download_folder(record) as first, \
                matx_import._download_folder(record) as second:
            self.assertNotEqual(first, second, "two library imports share one download")

    def test_on26_import_to_scene_keeps_its_download_in_hip_tex_as_write_paths_as_says(self):
        test_support.pin_env(self, "OCIO", "/dev/null")
        test_support.hip_in_scratch(self)
        source, record, textures = simready(self)
        destination = hou.node("/mat") or hou.node("/").createNode("mat")
        with hou.undos.group("one step"):
            builder, why = matx_import.build_in_scene(record, source, None, destination,
                                                      path_style="hip")
        self.assertIsNotNone(builder, why)
        self.addCleanup(builder.destroy)
        images = [node.parm("file") for node in builder.children()
                  if node.type().name().startswith("mtlxtiledimage")]
        self.assertEqual(len(textures), len(images))
        self.assertEqual([], [p.unexpandedString() for p in images
                              if not p.unexpandedString().startswith("$HIP/tex/")
                              or not os.path.isfile(p.eval())])


if __name__ == "__main__":
    unittest.main()
