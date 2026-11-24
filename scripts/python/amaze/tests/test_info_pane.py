"""Info pane: one test per requirement in docs/requirements/info-pane.md."""

import datetime
import json
import os
import shutil
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")    # BEFORE the app ▸p/first-app-picks-the-platform
from PySide6 import QtCore, QtGui, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402
import numpy  # noqa: E402
import OpenImageIO as oiio  # noqa: E402

from amaze.core import code_library, conversion, cop_library, file_info, gradient_library  # noqa: E402
from amaze.core import image_preview, library, library_files, material, texstore, versions  # noqa: E402
from amaze.helpers import theme  # noqa: E402
from amaze.panel import info_panel  # noqa: E402
from amaze.sections import code as code_section, color as color_section  # noqa: E402
from amaze.sections import material as material_section, node as node_section  # noqa: E402
from amaze.tests import test_support  # noqa: E402

METAL, BRICKS = "139888336268658010", "139888336377945550"    # fixture materials
put = test_support.put


def picture(path, width, height, channels=3, kind=oiio.UINT8, value=0.5, names=None, mips=False,
            **attributes):
    """A flat picture of `value`; with `mips` a tiled file holding every smaller level."""
    spec = oiio.ImageSpec(width, height, channels, kind)
    if names:
        spec.channelnames = names
    for key, value_of in attributes.items():
        spec.attribute(key, value_of)
    buffer = oiio.ImageBuf(spec)
    buffer.set_pixels(oiio.ROI(0, width, 0, height),
                      numpy.full((height, width, channels), value, dtype=numpy.float32))
    written = (oiio.ImageBufAlgo.make_texture(oiio.MakeTxTexture, buffer, path) if mips
               else buffer.write(path))
    assert written, oiio.geterror()
    return path


def every_file(folder: str) -> dict:
    """Every file under `folder` and its bytes, scratch and backups included."""
    found = {}
    for here, _folders, names in os.walk(folder):
        for name in names:
            with open(os.path.join(here, name), "rb") as handle:
                found[os.path.relpath(os.path.join(here, name), folder)] = handle.read()
    return found


def section(cls, model):
    """A section over `model` behind a sorting proxy, so a proxy row is not its source row."""
    proxy = QtCore.QSortFilterProxyModel()
    proxy.setSourceModel(model)
    proxy.sort(0, QtCore.Qt.SortOrder.DescendingOrder)
    pane = types.SimpleNamespace(**{cls.model_attr: model, cls.proxy_attr: proxy,
                                    cls.category_attr: object()})
    made = cls(pane)
    made.proxy = proxy    # kept alive with the section
    made.index = lambda row: proxy.mapFromSource(model.index(row, 0))
    return made


class Asks(QtCore.QObject):
    """A reader that records each ask; `answer`, when set, is emitted at once."""

    ready = QtCore.Signal(str, object)

    def __init__(self):
        super().__init__()
        self.asked, self.stops, self.answer = [], 0, None

    def ask(self, key, what):
        self.asked.append((key, what))
        if self.answer is not None:
            self.ready.emit(key, self.answer)

    def stop(self):
        self.stops += 1


class Gate:
    """A stand-in read on the reader's thread: waits for `release` or a cancel, and records both."""

    def __init__(self, answer):
        self.answer, self.calls, self.release = answer, [], threading.Event()

    def __call__(self, what, *rest, cancelled=None):
        cancelled, seen = cancelled or rest[-1], threading.Event()
        self.calls.append((what, threading.current_thread(), seen))
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not self.release.is_set():
            if cancelled():
                seen.set()
                return None
            time.sleep(0.01)
        return self.answer


class _Info(unittest.TestCase):
    """A fixture library, a scratch folder of files, and an info pane with recording readers."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.prefs = test_support.fixture_prefs(self)
        self.dir = tempfile.mkdtemp(prefix="amaze_info_")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def at(self, name: str) -> str:
        return os.path.join(self.dir, name)

    def materials(self):
        model = library.MaterialLibrary(self.prefs)
        return model, section(material_section.MaterialSection, model)

    def folder_of(self, model, mat_id: str) -> str:
        return model.asset_directories(mat_id)["folder"]

    def pane(self):
        rows, pictures = Asks(), Asks()
        pane = info_panel.InfoPanel(types.SimpleNamespace(), rows, pictures=pictures)
        self.addCleanup(pane.deleteLater)
        self.addCleanup(pane.hide)
        pane.resize(400, 900)
        pane.show()
        QtWidgets.QApplication.processEvents()
        return pane, rows, pictures

    def file_subject(self, path: str, key: str = "", before=(("Name", "a"),)):
        return file_info.Subject(key or path, "a", "EXR", before, (),
                                 file_info.request_for_file(path))

    def gated(self, module, answer):
        """`module.read` replaced by a Gate until the test ends, its threads waited for."""
        gate = Gate(answer)
        patch = mock.patch.object(module, "read", gate)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(test_support.pump_until, lambda: not file_info.engine._threads, 5.0)
        self.addCleanup(gate.release.set)
        return gate

    def usd_with_payload(self) -> str:
        put(self.dir, "inner.usda", '#usda 1.0\n(\n    defaultPrim = "root"\n)\n'
            'def Xform "root"\n{\n    def Xform "b" {}\n    def Xform "c" {}\n}\n')
        return put(self.dir, "shot.usda", '#usda 1.0\n(\n    defaultPrim = "a"\n'
                   '    startTimeCode = 1\n    endTimeCode = 240\n    timeCodesPerSecond = 24\n'
                   '    upAxis = "Z"\n    metersPerUnit = 0.01\n)\n'
                   'def Xform "a" (\n    payload = @./inner.usda@\n)\n{\n}\ndef Xform "d" {}\n')

    def box(self, name: str = "box.bgeo.sc") -> str:
        geometry = hou.Geometry()
        hou.sopNodeTypeCategory().nodeVerbs()["box"].execute(geometry, [])
        geometry.saveToFile(self.at(name))
        return self.at(name)


class FactsTest(_Info):

    def test_in01_showing_facts_or_a_picture_writes_nothing(self):
        files = [picture(self.at("a.exr"), 64, 32, kind=oiio.HALF), picture(self.at("b.png"), 8, 8),
                 picture(self.at("c.tx"), 64, 64, mips=True), self.box(), self.usd_with_payload()]
        model, materials = self.materials()
        row = model.find_asset_row_by_id(METAL)
        os.makedirs(os.path.join(self.folder_of(model, METAL), "textures"))
        shutil.copy(files[1], os.path.join(self.folder_of(model, METAL), "textures", "t.png"))
        model._assets[row]._extra["textures"] = [texstore.OWN_PREFIX + "textures/t.png"]
        before = every_file(self.dir), every_file(self.prefs.dir)
        for path in files:
            file_info.read(file_info.request_for_file(path))
            image_preview.read(path, 32)
        subject = materials.info_subject(materials.index(row))
        file_info.read(subject.request)
        rows = [materials.index(r) for r in range(model.rowCount())]
        file_info.read(materials.info_subject_for(rows).request)
        self.assertEqual(before, (every_file(self.dir), every_file(self.prefs.dir)))

    def test_in10_reading_facts_never_holds_up_houdini(self):
        self.assertEqual(10000, file_info.TOOL_TIMEOUT_MS)
        hung = [test_support.plain_python(), "-c", "import time; time.sleep(30)"]
        with mock.patch.object(file_info, "TOOL_TIMEOUT_MS", 300):
            start = time.monotonic()
            self.assertIsNone(file_info.run_tool(hung[0], hung[1:], lambda: False))
        self.assertLess(time.monotonic() - start, 3.0, "a hung tool held the read up")
        self.assertFalse([p for p in conversion._ABANDONED if list(p.args) == hung], "not killed")
        rows = dict(file_info.read(file_info.request_for_file(self.usd_with_payload())))
        self.assertEqual("1", rows["Prims"], "the USD file was opened with its payload")

        gate = self.gated(file_info, [("Read", "rows")])
        got, reader = [], file_info.Reader()
        reader.ready.connect(lambda key, rows: got.append(key))
        reader.ask("a", file_info.Request(file_info.KIND_SIZES, ("/a",)))
        self.assertTrue(test_support.pump_until(lambda: gate.calls, 2.0))
        reader.ask("b", file_info.Request(file_info.KIND_SIZES, ("/b",)))
        self.assertTrue(gate.calls[0][2].wait(2.0), "a changed selection did not stop the read")
        self.assertTrue(test_support.pump_until(lambda: len(gate.calls) == 2, 2.0))
        self.assertIsNot(threading.main_thread(), gate.calls[1][1], "read on the UI thread")
        file_info.engine.shutdown()    # what quitting Houdini runs
        self.assertTrue(gate.calls[1][2].is_set(), "quitting did not stop the read")
        test_support.pump_until(lambda: False, 0.2)
        self.assertEqual([], got)

        pane, rows, _pictures = self.pane()
        pane.hide()
        pane.set_subject(self.file_subject("/lib/a.bgeo.sc"))
        self.assertEqual([], rows.asked, "a hidden pane read a file")

    def test_in20_facts_for_an_earlier_selection_are_never_shown(self):
        gate = self.gated(file_info, [("Read", "rows")])
        got, reader = [], file_info.Reader()
        reader.ready.connect(lambda key, rows: got.append(key))
        reader.ask("a", file_info.Request(file_info.KIND_SIZES, ("/a",)))
        reader.ask("b", file_info.Request(file_info.KIND_SIZES, ("/b",)))
        gate.release.set()
        self.assertTrue(test_support.pump_until(lambda: got, 3.0))
        test_support.pump_until(lambda: not file_info.engine._threads, 3.0)
        self.assertEqual(["b"], got)

        pane, rows, _pictures = self.pane()
        pane.set_subject(self.file_subject("/lib/a.bgeo.sc", "k1"))
        second = self.file_subject("/lib/b.bgeo.sc", "k2", (("Name", "b"),))
        pane.set_subject(second)
        rows.ready.emit("k1", [("Points", "8")])
        self.assertEqual(second.before, pane.rows())

    def test_in21_a_materials_or_nodes_size_is_its_whole_folder(self):
        model, materials = self.materials()
        cops = cop_library.CopLibrary(self.prefs)
        nodes = section(node_section.CopSection, cops)
        node_row = cops._append_record(cops._asset_from_row({"id": "node01", "name": "Rig"}))
        put(self.folder_of(cops, "node01"), "node01.mat", b"n" * 2000)
        for (model_of, chosen, mat_id) in ((model, materials, METAL), (cops, nodes, "node01")):
            folder = self.folder_of(model_of, mat_id)
            for name, size in (("versions/%s_1.mat" % mat_id, 3 << 20), ("versions/versions.json", 90),
                               ("textures/wood.png", 5000), ("source.zip", 7000),
                               ("comments/shot.png", 600)):
                put(folder, name, b"x" * size)
            whole = sum(len(data) for data in every_file(folder).values())
            row = model_of.find_asset_row_by_id(mat_id) if model_of is model else node_row
            with self.subTest(section=model_of.DB_FILENAME):
                self.assertIn(("Size", file_info.size_text(whole)),
                              chosen.info_subject(chosen.index(row)).before)

    def test_in22_a_material_shows_its_textures_and_the_largest(self):
        model, materials = self.materials()
        row = model.find_asset_row_by_id(METAL)
        folder = self.folder_of(model, METAL)
        os.makedirs(os.path.join(folder, "textures"))
        picture(os.path.join(folder, "textures", "a.png"), 64, 32)
        picture(os.path.join(folder, "textures", "b.exr"), 40, 40, kind=oiio.HALF)
        model._assets[row]._extra["textures"] = [
            texstore.OWN_PREFIX + "textures/" + name for name in ("a.png", "b.exr", "gone.png")]
        subject = materials.info_subject(materials.index(row))
        self.assertIn(("Textures", "2 files"), subject.before)
        self.assertEqual([("Largest Texture", "64 x 32")], file_info.read(subject.request))

    def test_in23_an_asset_shows_its_name_date_licence_version_and_id(self):
        model, materials = self.materials()
        row = model.find_asset_row_by_id(METAL)
        before = materials.info_subject(materials.index(row))
        self.assertEqual((("Name", "Metal"), ("Date", "2026-01-27")), before.before[:2])
        self.assertEqual((("ID", METAL),), before.after, "an empty licence or version has a row")
        for named, shown in (("glossy", (("Version", "glossy"),)), ("Metal", ())):
            put(versions.versions_dir(self.prefs, METAL), versions.LEDGER,
                json.dumps({"active": 1, "versions": [{"n": 1, "name": named}]}))
            model, materials = self.materials()
            model._assets[model.find_asset_row_by_id(METAL)].license = "MIT"
            after = materials.info_subject(materials.index(model.find_asset_row_by_id(METAL))).after
            with self.subTest(version=named):
                self.assertEqual(shown + (("License", "MIT"), ("ID", METAL)), after)

    def test_in24_each_section_shows_its_own_facts(self):
        model, materials = self.materials()
        facts = materials.info_subject(materials.index(model.find_asset_row_by_id(METAL))).before
        self.assertIn(("Renderer", "MaterialX"), facts)
        cops = cop_library.CopLibrary(self.prefs)
        row = cops._append_record(cops._asset_from_row({"id": "n1", "name": "Rig", "renderer": "Cop"}))
        nodes = section(node_section.CopSection, cops)
        self.assertIn(("Context", "Cop"), nodes.info_subject(nodes.index(row)).before)
        snippets = code_library.CodeLibrary(self.prefs)
        mat_id = snippets.add_snippet("int a = 1;\n\nf@x = a;\n", "Sum", "VEX", "", "")
        code = section(code_section.CodeSection, snippets)
        self.assertEqual((("Language", "VEX"), ("Lines", "3")), code.info_subject(
            code.index(snippets.find_asset_row_by_id(mat_id))).before[2:])
        colors = gradient_library.GradientLibrary(self.prefs)
        swatches = [{"name": "Ink", "hex": "#1b1b1b"}, {"name": "Sky", "hex": "#5d7abd"}]
        row = colors._append_record(colors._asset_from_row(
            {"name": "Dusk", "colors": swatches, "ramp": {"keys": [0.0, 1.0], "bases": ["Linear"] * 2,
                                                          "values": [[0, 0, 0], [1, 1, 1]]}}))
        palette = section(color_section.GradientSection, colors)
        self.assertEqual((("Colors", "2"), ("Values", "#1B1B1B  #5D7ABD"), ("Interpolation", "Linear")),
                         palette.info_subject(palette.index(row)).before[1:])

    def test_in25_a_file_shows_its_name_dates_size_format_and_folder(self):
        path = put(self.dir, "cache.bgeo.sc", b"g" * 2048)
        before, after = file_info.file_rows(path)
        dated = [("Created", datetime.date.today().isoformat())] if hasattr(os.stat(path),
                                                                         "st_birthtime") else []
        self.assertEqual([("Name", "cache")] + dated + [
            ("Modified", datetime.date.today().isoformat()), ("Size", "2 KB"),
            ("Format", "BGEO.SC")], list(before))
        self.assertEqual((("Folder", self.dir),), after)
        self.assertEqual(((("Name", "gone"), ("Format", "PNG")), (("Folder", self.dir),)),
                         file_info.file_rows(self.at("gone.png")))

    def test_in26_a_picture_adds_its_header_facts(self):
        exr = picture(self.at("a.exr"), 16, 8, kind=oiio.HALF, compression="zip")
        self.assertEqual({"Dimensions": "16 x 8", "Color Space": "Linear", "Bit Depth": "16 bit float",
                          "Channels": "RGB", "Compression": "ZIP", "MIP Maps": "No"},
                         dict(file_info.read(file_info.request_for_file(exr))))
        tx = dict(file_info.read(file_info.request_for_file(picture(self.at("b.tx"), 64, 64, mips=True))))
        self.assertEqual(("64 x 64", "Yes"), (tx["Dimensions"], tx["MIP Maps"]))
        rat = os.path.join(os.environ["HFS"], "houdini", "pic", "Mandril.rat")    # iinfo reads it
        self.assertEqual([("Dimensions", "256 x 256"), ("Color Space", "sRGB"),
                          ("Bit Depth", "8 bit integer"), ("Channels", "RGBA"), ("MIP Maps", "Yes")],
                         file_info.read(file_info.request_for_file(rat)))

    def test_in27_a_geometry_or_usd_file_adds_its_facts(self):
        rows = dict(file_info.read(file_info.request_for_file(self.box())))
        self.assertEqual(("8", "24", "6 Polygons", "P", "1 x 1 x 1"),
                         (rows["Points"], rows["Vertices"], rows["Primitives"],
                          rows["Attributes"], rows["Dimensions"]))
        self.assertTrue(rows["Saved With"].startswith("Houdini "))
        self.assertEqual([("Prims", "1"), ("Layers", "2"), ("Default Prim", "/a"), ("Up Axis", "Z"),
                          ("Meters Per Unit", "0.01"), ("Frames", "1 - 240, 24 fps")],
                         file_info.read(file_info.request_for_file(self.usd_with_payload())))

    def test_in28_several_items_show_their_count_and_their_whole_size(self):
        model, materials = self.materials()
        rows = [model.find_asset_row_by_id(mat_id) for mat_id in (METAL, BRICKS)]
        put(self.folder_of(model, BRICKS), "versions/old.mat", b"v" * 4096)
        subject = materials.info_subject_for([materials.index(row) for row in rows])
        self.assertEqual(("2 items selected", (("Items", "2"),)), (subject.name, subject.before))
        whole = sum(len(data) for mat_id in (METAL, BRICKS)
                    for data in every_file(self.folder_of(model, mat_id)).values())
        self.assertEqual([("Size", file_info.size_text(whole))], file_info.read(subject.request))


class PictureTest(_Info):

    def test_in11_reading_a_picture_never_holds_up_houdini(self):
        names = ["R", "G", "B", "A"] + ["pass%d" % n for n in range(6)]
        path = picture(self.at("passes.exr"), 512, 512, 10, oiio.HALF, names=names, mips=True)
        reads, real = [], oiio.ImageInput

        class Opened:
            def __init__(self, source):
                self.source = source

            def __getattr__(self, name):
                return getattr(self.source, name)

            def read_image(self, *args):
                reads.append(args)
                return self.source.read_image(*args)

        with mock.patch.object(oiio, "ImageInput", types.SimpleNamespace(
                open=lambda name: Opened(real.open(name)))):
            self.assertIsNotNone(image_preview.read(path, 100))
        self.assertEqual([(0, 2, 0, 4, oiio.HALF)], reads, "512, 256, 128: level 2, RGBA only")

        gate = self.gated(image_preview, None)
        got, reader = [], image_preview.Reader()
        reader.ready.connect(lambda key, image: got.append(key))
        reader.ask("/a.exr", 100)
        self.assertTrue(test_support.pump_until(lambda: gate.calls, 2.0))
        reader.ask("/b.exr", 100)
        self.assertTrue(gate.calls[0][2].wait(2.0), "a changed selection did not stop the read")
        self.assertTrue(test_support.pump_until(lambda: len(gate.calls) == 2, 2.0))
        self.assertIsNot(threading.main_thread(), gate.calls[1][1], "read on the UI thread")
        file_info.engine.shutdown()    # what quitting Houdini runs
        self.assertTrue(gate.calls[1][2].is_set(), "quitting did not stop the read")
        self.assertEqual([], got)

        pane, _rows, pictures = self.pane()
        pane.set_subject(self.file_subject("/lib/a.exr"))
        stops = pictures.stops
        pane.hide()
        self.assertGreater(pictures.stops, stops, "hiding the pane did not stop the read")
        pane.set_subject(self.file_subject("/lib/b.exr"))
        pane.show()
        pane.toggle_preview()    # the picture off
        pane.set_subject(self.file_subject("/lib/c.exr"))
        self.assertEqual(["/lib/a.exr"], [path for path, _width in pictures.asked])

    def test_in29_a_picture_shows_at_the_panes_width_upright_in_its_own_shape(self):
        pane, _rows, pictures = self.pane()
        pane.set_subject(self.file_subject("/lib/a.exr"))
        wide = round(pane.body_widget.width() * theme.screen_ratio(pane))
        self.assertEqual([("/lib/a.exr", wide)], pictures.asked)
        shaped = image_preview.read(picture(self.at("a.exr"), 400, 200, kind=oiio.HALF), 100)
        self.assertEqual((100, 50), (shaped.width(), shaped.height()))
        picture(self.at("turned.jpg"), 400, 200, Orientation=6)    # stored lying down, turned by its flag
        upright = image_preview.read(self.at("turned.jpg"), 100)
        self.assertEqual((100, 200), (upright.width(), upright.height()))
        alpha = image_preview.read(picture(self.at("cut.png"), 8, 8, 4), 8)
        self.assertTrue(alpha.hasAlphaChannel())
        grey = image_preview.read(picture(self.at("y.exr"), 8, 8, 1, oiio.HALF, names=["Y"]), 8)
        self.assertEqual(QtGui.QImage.Format.Format_Grayscale8, grey.format())
        scene = image_preview.read(picture(self.at("s.exr"), 8, 8, kind=oiio.HALF, value=0.18), 8)
        shown = image_preview.read(picture(self.at("s.tif"), 8, 8, value=0.18), 8)
        self.assertAlmostEqual(46, shown.pixelColor(4, 4).red(), delta=1)    # 0.18 of 255, as it is
        self.assertGreater(scene.pixelColor(4, 4).red(), 80, "scene values skipped the display view")

    def test_in30_the_picture_shown_is_of_the_file_selected_now(self):
        pane, _rows, pictures = self.pane()
        pane.set_subject(self.file_subject("/lib/a.exr"))
        pane.set_subject(self.file_subject("/lib/b.exr"))
        pictures.ready.emit("/lib/a.exr", QtGui.QImage(40, 20, QtGui.QImage.Format.Format_RGB888))
        self.assertIsNone(pane.preview.image(), "a late picture of another file was shown")
        pictures.answer = QtGui.QImage(40, 20, QtGui.QImage.Format.Format_RGB888)
        pane.set_subject(self.file_subject("/lib/c.exr"))
        pictures.answer = None
        pane.set_subject(self.file_subject("/lib/d.exr"))
        self.assertIsNone(pane.preview.image(), "the last file's picture stayed")

    def test_in31_no_decoded_picture_is_kept(self):
        pane, _rows, pictures = self.pane()
        pictures.answer = QtGui.QImage(40, 20, QtGui.QImage.Format.Format_RGB888)
        pane.set_subject(self.file_subject("/lib/a.exr"))
        pane.toggle_preview()
        self.assertIsNone(pane.preview.image(), "a hidden picture was kept")
        pane.toggle_preview()
        pane.hide()
        self.assertIsNone(pane.preview.image(), "a hidden pane kept its picture")
        pane.show()
        pane.set_subject(self.file_subject("/lib/a.exr"))
        pane.set_subject(self.file_subject("/lib/a.exr", before=(("Size", "2 KB"),)))    # changed
        self.assertEqual(4, len(pictures.asked), "a picture was shown again without a read")
        path = picture(self.at("a.png"), 40, 20)
        self.assertEqual(40, image_preview.read(path, 100).width())
        picture(path, 60, 20)
        self.assertEqual(60, image_preview.read(path, 100).width(), "the old picture was kept")

    def test_in32_a_wider_pane_reads_the_picture_again_once_the_drag_stops(self):
        pane, _rows, pictures = self.pane()
        for whole, asks in ((False, 1), (True, 0)):
            image = QtGui.QImage(200, 100, QtGui.QImage.Format.Format_RGB888)
            if whole:
                image.setText(image_preview.WHOLE, "1")
            pictures.answer = image
            pane.set_subject(self.file_subject("/lib/%s.exr" % whole))
            pictures.asked.clear()
            pane.resize(pane.width() + 40, pane.height())
            pane.resize(pane.width() + 40, pane.height())
            QtWidgets.QApplication.processEvents()
            self.assertEqual([], pictures.asked, "the read did not wait for the drag to stop")
            test_support.pump_until(lambda: False, info_panel.WIDER_READ_MS * 3 / 1000)
            with self.subTest(whole=whole):
                self.assertEqual(asks, len(pictures.asked))


if __name__ == "__main__":
    unittest.main()
