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

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

from amaze import messages  # noqa: E402
from amaze.core import (debug, matx_import, matx_library, matx_sources,  # noqa: E402
                        matx_translate, notes, packages)
from amaze.render import thumbs  # noqa: E402
from amaze.tests import test_support  # noqa: E402

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


class _Listing(matx_sources.MatxSource):
    """A source listing one material named after it, or one that cannot be reached."""

    def __init__(self, name: str, reached: bool = True) -> None:
        self.name, self.reached = name, reached

    def list_materials(self, search="", offset=0, limit=60):
        if not self.reached:
            raise urllib.error.URLError("no route to host")
        return [matx_sources.MatxRecord(source=self.name, uid="m", title="From " + self.name)]


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

    def test_on20_each_source_lists_and_one_not_reached_is_named_while_the_others_list(self):
        sources = [_Listing("Brick Works"), _Listing("Gone Site", reached=False),
                   _Listing("Stone Yard")]
        with mock.patch.object(matx_sources, "all_sources", lambda: sources), \
                test_support.captured_log() as log:
            model = matx_library.MatxOnlineLibrary()
            self.addCleanup(model.shutdown)
            model.reload(force=True)
            test_support.pump_until(lambda: not model._loading)
        self.assertEqual(["From Brick Works", "From Stone Yard"], sorted(
            model.index(row, 0).data() for row in range(model.rowCount())))
        self.assertEqual(1, sum("Gone Site" in line for line in log.messages("refuse")),
                         log.messages(None))

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

    def test_on24_a_missing_texture_is_matched_by_name_or_named_and_the_rest_imports(self):
        class Short(_Fetch):    # the document names three textures; the download holds a.jpg and b.png

            def fetch(self, record, resolution, dest, progress=None):
                test_support.put(dest, "a.jpg", b"a")
                test_support.put(dest, "b.png", b"b")
                return {"mtlx": test_support.put(dest, "m.mtlx", '<materialx version="1.38">%s</materialx>' % "".join(
                    '<input value="%s"/>' % name for name in ("a.jpg", "b.jpg", "tex/c.jpg")))}

        dest = os.path.join(self.dir, "tex", "brick")
        with test_support.captured_log() as log:
            produce, _note, error = matx_import._producer_for(self.record(), Short(), "1k", dest)
        self.assertEqual((True, ""), (produce is not None, error), "the rest did not import")
        with open(os.path.join(dest, "m.mtlx"), encoding="utf-8") as handle:
            self.assertIn('value="b.png"', handle.read(), "b.jpg was not matched by its name")
        self.assertEqual([messages.DOWNLOAD_TEXTURES_MISSING % ("Brick", "c.jpg")], log.messages())

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


class _Measured(matx_sources.MatxSource):
    """A source of measured materials: a record's uid `fails` cannot be had, `esc` is stopped."""

    name = "Measured"

    @staticmethod
    def page_url(record) -> str:
        return "https://example.invalid/" + record.uid

    @staticmethod
    def fetch(record, resolution, dest, progress=None):
        if record.uid == "fails":
            raise OSError("the site sent nothing")
        if record.uid == "esc":
            raise hou.OperationInterrupted()
        return {"values": {"color": [0.5, 0.4, 0.3]}}


def measured(uid: str, title: str) -> matx_sources.MatxRecord:
    return matx_sources.MatxRecord(source="Measured", uid=uid, title=title, author="A. Mason",
                                   category="Stone", tags=["rough", "red"], licence="CC0",
                                   kind="values")


class InThePaneTest(unittest.TestCase):
    """A pane on a fixture library, the Measured source among its online ones; each message kept."""

    def setUp(self):
        test_support.pin_env(self, "OCIO", "/dev/null")    # the save checks it
        self.pane = test_support.fixture_pane(self)
        self.pane.prefs.render_on_import = 1
        sources, source = self.pane.matx_online_model.sources, _Measured()
        sources.append(source)
        self.addCleanup(sources.remove, source)
        self.model, self.said, self.rendered = self.pane.material_model, [], []
        ui = types.SimpleNamespace(displayMessage=lambda text, details="", **how: self.said.append(
            (text, details)), setStatusMessage=lambda *a, **k: None)
        for patcher in (mock.patch.object(hou, "ui", ui, create=True), mock.patch.object(
                thumbs.ThumbNailRenderer, "render_assets", lambda prefs, made: self.rendered.extend(
                    str(each.mat_id) for each in made))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_on23_the_new_material_has_its_renderer_fields_and_a_credit_comment(self):
        target = next((key for key in ("Redshift", "Octane") if test_support.renderer_loaded(key)), "")
        for renderer in ("Karma",) + ((target,) if target else ()):
            before = test_support.asset_ids(self.model)
            ok, why = matx_import.import_record(
                measured("brick-7", "Brick"), _Measured(), None, self.model, self.pane.prefs,
                renderer=renderer, save=self.pane.saving.import_save(), render=False)
            self.assertTrue(ok, why)
            made, = test_support.arrived(self.model, before)
            row = made.get_as_dict()
            self.assertEqual((renderer, "Brick", ["Stone"], ["rough", "red"], "CC0", "Measured",
                              "brick-7"), (row["renderer"], row["name"], self.model.named_categories(
                                  made), row["tags"], row["license"], row["source"], row["online_uid"]))
            credit = notes.note_for(self.pane.prefs, notes.note_key("material", made.mat_id))
            self.assertTrue(all(part in credit["items"][0]["text"] for part in (
                "Measured", "A. Mason", "https://example.invalid/brick-7")), credit)

    def test_on25_a_failing_record_stops_nothing_one_message_names_it_and_esc_keeps_the_saved(self):
        before = test_support.asset_ids(self.model)
        self.pane.online_import.import_records([measured("a", "Granite"), measured(
            "fails", "Basalt"), measured("b", "Marble")])
        self.assertEqual(["Granite", "Marble"], sorted(
            made.name for made in test_support.arrived(self.model, before)))
        self.assertEqual([(messages.AMAZE_COULD_NOT % (1, 3), "Basalt: ")], [
            (text, details[:len("Basalt: ")]) for text, details in self.said])
        before, self.rendered[:] = test_support.asset_ids(self.model), []
        self.pane.online_import.import_records([measured("c", "Slate"), measured(
            "esc", "Onyx"), measured("d", "Chalk")])
        saved = test_support.arrived(self.model, before)
        self.assertEqual((["Slate"], [str(made.mat_id) for made in saved]), (
            [made.name for made in saved], self.rendered), "after Esc it is gone, or no picture")

    def test_on27_generate_builds_one_material_in_one_undo_step_and_adds_nothing(self):
        library = test_support.library_state(self.pane.prefs.dir)
        builders = {node.path() for node in hou.node("/").allSubChildren() if node.comment()}
        undos = hou.undos.undoLabels()
        self.pane.loading.generate_random_material()
        made = [node for node in hou.node("/").allSubChildren()
                if node.comment() and node.path() not in builders]
        for node in made:
            self.addCleanup(test_support.drop_node, node)
        self.assertEqual(1, len(made), [node.path() for node in made])
        self.assertTrue(made[0].comment().startswith("Generated from "), made[0].comment())
        self.assertEqual(("Amaze Generate Material",), hou.undos.undoLabels()[:len(
            hou.undos.undoLabels()) - len(undos)])
        self.assertEqual(library, test_support.library_state(self.pane.prefs.dir))

if __name__ == "__main__":
    unittest.main()
