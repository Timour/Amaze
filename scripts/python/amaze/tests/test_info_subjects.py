"""The info pane's rows per section: `info_subject` for one row, `info_subject_for` for several."""

import datetime
import json
import os
import shutil
import sys
import tempfile
import types
import unittest

sys.path.insert(    # three dirnames up: the dev tree, not the install
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # BEFORE the app exists ▸p/first-app-picks-the-platform
from PySide6 import QtCore, QtGui, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401
from amaze.core import (code_library, cop_library, file_info, file_library,  # noqa: E402
                        gradient_library, library, library_files, material, texstore,
                        thumbnails, versions)
from amaze.sections import code as code_section, color as color_section, file as file_section, material as material_section, node as node_section, online as online_section, base as section_base  # noqa: E402
from amaze.tests import test_support  # noqa: E402

METAL = "139888336268658010"    # fixture materials, each with a .json, a .mat and a .png
BRICKS = "139888336377945550"


def _labels(rows) -> list:
    return [label for label, _value in rows]


def _write(path: str, data: bytes) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    return path


def _section(cls, model, **attrs):
    """A section over `model` behind a sorting proxy, so a proxy row is not its source row."""
    proxy = QtCore.QSortFilterProxyModel()
    proxy.setSourceModel(model)
    proxy.sort(0, QtCore.Qt.SortOrder.DescendingOrder)
    panel = types.SimpleNamespace(**attrs)
    if issubclass(cls, file_section.FolderSection):
        setattr(panel, cls.files_attr, model)
        setattr(panel, cls.proxy_attr, proxy)
    else:
        setattr(panel, cls.model_attr, model)
        setattr(panel, cls.proxy_attr, proxy)
        setattr(panel, cls.category_attr, object())
    section = cls(panel)
    section.proxy = proxy    # kept alive with the section
    return section


def _index(section, row: int):
    """The proxy index of source `row`."""
    return section.proxy.mapFromSource(section.proxy.sourceModel().index(row, 0))


def _sizes(paths) -> str:
    return file_info.size_text(sum(os.path.getsize(path) for path in paths))


class LibraryCase(unittest.TestCase):

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.prefs = test_support.fixture_prefs(self)

    def _material_section(self):
        model = library.MaterialLibrary(self.prefs)
        return model, _section(material_section.MaterialSection, model)

    def _textures(self, folder: str, names) -> list:
        """Texture files in the library's store, as the tokens a record lists."""
        tokens = []
        for number, name in enumerate(names):
            path = _write(os.path.join(texstore.store_dir(self.prefs), folder, "textures", name),
                          b"x" * (100 * (number + 1)))
            tokens.append(texstore.tokenize(path, self.prefs))
        return tokens


class MaterialRowsTest(LibraryCase):

    def _ledger(self, mat_id: str, ledger: dict) -> None:
        """A version ledger on disk, before the model reads which ids have one."""
        folder = versions.versions_dir(self.prefs, mat_id, versions.MATERIAL)
        _write(os.path.join(folder, versions.LEDGER), json.dumps(ledger).encode("utf-8"))

    def test_a_material_with_textures_a_version_and_a_license(self):
        self._ledger(METAL, {"active": 2, "versions": [{"n": 1}, {"n": 2}]})
        model, section = self._material_section()
        row = model.find_asset_row_by_id(METAL)
        asset = model._assets[row]
        tokens = self._textures("Metal", ("base.png", "rough.png"))
        asset._extra["textures"] = tokens + ["$AMAZELIB/matX/Metal/textures/gone.png"]
        asset.license = "CC0"
        subject = section.info_subject(_index(section, row))

        textures = [texstore.resolve(token, self.prefs) for token in tokens]
        own = [path for path in model.asset_files(METAL).values() if os.path.isfile(path)]
        self.assertEqual(3, len(own), "the fixture material has no .json, .mat and .png")
        self.assertEqual((("Name", "Metal"),
                          ("Date", "2026-01-27"),
                          ("Size", _sizes(own + textures)),
                          ("Renderer", "MaterialX"),
                          ("Textures", "2 files")), subject.before)
        self.assertEqual((("Version", "2"), ("License", "CC0"), ("ID", METAL)), subject.after)
        self.assertEqual(file_info.Request(file_info.KIND_TEXTURES, tuple(textures)),
                         subject.request, "the read is not given the texture files that exist")
        comment = section.comment_subject(_index(section, row))
        self.assertEqual((comment.name, comment.type), (subject.name, subject.type),
                         "the header differs from the comments pane's")
        self.assertEqual("material:" + METAL, subject.key)

    def test_a_material_without_textures_has_no_textures_row_and_no_read(self):
        model, section = self._material_section()
        row = model.find_asset_row_by_id(BRICKS)
        subject = section.info_subject(_index(section, row))
        self.assertEqual(["Name", "Date", "Size", "Renderer"], _labels(subject.before))
        self.assertIsNone(subject.request)
        self.assertEqual((("ID", BRICKS),), subject.after,
                         "an empty License or Version still has a row")

    def test_a_named_version_shows_its_name(self):
        self._ledger(METAL, {"active": 1, "versions": [{"n": 1, "name": "glossy"}]})
        model, section = self._material_section()
        row = model.find_asset_row_by_id(METAL)
        self.assertEqual("glossy", model.data(model.index(row, 0), model.ActiveVersionRole))
        self.assertEqual((("Version", "glossy"), ("ID", METAL)),
                         section.info_subject(_index(section, row)).after)

    def test_a_version_named_as_the_asset_has_no_version_row(self):
        self._ledger(METAL, {"active": 1, "versions": [{"n": 1, "name": "Metal"}]})
        model, section = self._material_section()
        row = model.find_asset_row_by_id(METAL)
        self.assertEqual(["ID"], _labels(section.info_subject(_index(section, row)).after),
                         "a version named as its asset repeats the Name row")


class NodeRowsTest(LibraryCase):

    def test_a_node_reports_its_files_and_its_context(self):
        model = cop_library.CopLibrary(self.prefs)
        section = _section(node_section.CopSection, model)
        asset = model._asset_from_row({"id": "nodeasset01", "name": "Blur Rig",
                                       "renderer": "Cop", "date": "2026-09-04 11:12:13",
                                       "license": "MIT"})
        row = model._append_record(asset)
        payload = _write(material.payload_path(self.prefs, "nodeasset01", self.prefs.ext,
                                               library_files.NODES), b"n" * 3000)
        subject = section.info_subject(_index(section, row))
        self.assertEqual((("Name", "Blur Rig"), ("Date", "2026-09-04"),
                          ("Size", _sizes([payload])), ("Context", "Cop")), subject.before)
        self.assertEqual((("License", "MIT"), ("ID", "nodeasset01")), subject.after)
        self.assertIsNone(subject.request)
        self.assertEqual(("Blur Rig", "Cop"), (subject.name, subject.type))


class CodeRowsTest(LibraryCase):

    def test_a_snippet_reports_its_language_and_its_lines(self):
        model = code_library.CodeLibrary(self.prefs)
        section = _section(code_section.CodeSection, model)
        mat_id = model.add_snippet("int a = 1;\nint b = 2;\n\nf@x = a + b;\n", "Sum",
                                   "VEX", "", "")
        row = model.find_asset_row_by_id(mat_id)
        subject = section.info_subject(_index(section, row))
        self.assertEqual((("Name", "Sum"),
                          ("Date", datetime.date.today().isoformat()),
                          ("Language", "VEX"), ("Lines", "4")), subject.before)
        self.assertEqual((("ID", mat_id),), subject.after)
        self.assertIsNone(subject.request)


class ColorRowsTest(LibraryCase):

    COLORS = [{"name": "Ink", "hex": "#1b1b1b"}, {"name": "Sky", "hex": "#5d7abd"}]

    def _subject(self, colors, ramp):
        model = gradient_library.GradientLibrary(self.prefs)
        section = _section(color_section.GradientSection, model)
        row = model._append_record(model._asset_from_row(
            {"name": "Dusk", "date": "2026-05-06 07:08:09", "license": "CC BY",
             "colors": colors, "ramp": ramp}))
        return section.info_subject(_index(section, row))

    def test_a_banded_palette_is_constant(self):
        subject = self._subject(self.COLORS, gradient_library._palette_ramp_data(self.COLORS))
        self.assertEqual((("Name", "Dusk"), ("Date", "2026-05-06"), ("Colors", "2"),
                          ("Values", "#1B1B1B  #5D7ABD"), ("Interpolation", "Constant")),
                         subject.before)
        self.assertEqual(["License", "ID"], _labels(subject.after),
                         "Colors keep no versions, so there is no Version row")
        self.assertIsNone(subject.request)
        self.assertEqual(("Dusk", "Gradient"), (subject.name, subject.type))

    def test_a_ramp_shows_its_basis_by_the_menu_label(self):
        for bases, shown in ((["CatmullRom", "CatmullRom"], "Catmull-Rom"),
                             (["MonotoneCubic"] * 2, "Monotone Cubic"),
                             (["BSpline"] * 2, "B-Spline"),
                             (["Linear", "Linear"], "Linear"),
                             (["Linear", "Bezier"], "Mixed")):
            with self.subTest(bases=bases):
                ramp = {"keys": [0.0, 1.0], "values": [[0, 0, 0], [1, 1, 1]], "bases": bases}
                self.assertEqual(("Interpolation", shown),
                                 self._subject(self.COLORS, ramp).before[-1])

    def test_a_palette_without_a_date_has_no_date_row(self):
        model = gradient_library.GradientLibrary(self.prefs)
        section = _section(color_section.GradientSection, model)
        row = model._append_record(model._asset_from_row(
            {"name": "Old", "colors": self.COLORS}))
        self.assertEqual(["Name", "Colors", "Values", "Interpolation"],
                         _labels(section.info_subject(_index(section, row)).before))


class FileRowsTest(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="amaze_info_files_")
        self.addCleanup(shutil.rmtree, self.root, True)
        image = QtGui.QImage(8, 8, QtGui.QImage.Format.Format_RGB32)
        image.fill(QtGui.QColor("#336699"))
        self.assertTrue(image.save(os.path.join(self.root, "plate.png")))
        _write(os.path.join(self.root, "shot.hip"), b"h" * 64)
        _write(os.path.join(self.root, "gone.png"), b"g")
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.add_file_folder(self.root)
        self.model = file_library.FileFiles(self.prefs)
        self.addCleanup(thumbnails.engine.cancel_pending_converts)
        self.model.set_folder(self.root)
        self.section = _section(file_section.FileSection, self.model)

    def _row(self, name: str) -> int:
        names = [self.model.data(self.model.index(row, 0)) for row in range(self.model.rowCount())]
        return names.index(name)

    def _subject(self, name: str):
        return self.section.info_subject(_index(self.section, self._row(name)))

    def _path(self, name: str) -> str:
        return self.model.data(self.model.index(self._row(name), 0), self.model.PathRole)

    def test_an_image_has_the_files_rows_and_an_image_read(self):
        subject = self._subject("plate.png")
        path = self._path("plate.png")
        before, after = file_info.file_rows(path)
        self.assertEqual((before, after), (subject.before, subject.after))
        self.assertEqual(["Name", "Created", "Modified", "Size", "Format"], _labels(before))
        self.assertEqual(("Name", "plate"), before[0])
        self.assertEqual(file_info.Request(file_info.KIND_IMAGE, (path,)), subject.request)
        self.assertEqual(("plate", "PNG"), (subject.name, subject.type))
        self.assertEqual("file:" + self.model.file_key(self._row("plate.png")), subject.key)

    def test_a_scene_has_no_read(self):
        subject = self._subject("shot.hip")
        self.assertIsNone(subject.request)
        self.assertEqual(("shot", "Hip"), (subject.name, subject.type))
        self.assertIn(("Format", "HIP"), subject.before)

    def test_a_missing_file_has_its_name_and_format_only(self):
        os.remove(os.path.join(self.root, "gone.png"))
        subject = self._subject("gone.png")
        self.assertEqual((("Name", "gone"), ("Format", "PNG")), subject.before)
        self.assertEqual(["Folder"], _labels(subject.after))

    def test_several_files_are_counted_and_their_sizes_read(self):
        indexes = [_index(self.section, self._row(name)) for name in ("plate.png", "shot.hip")]
        subject = self.section.info_subject_for(indexes)
        self.assertEqual(("2 items selected", "", (("Items", "2"),), ()),
                         (subject.name, subject.type, subject.before, subject.after))
        self.assertEqual(file_info.KIND_SIZES, subject.request.kind)
        self.assertEqual({self._path("plate.png"), self._path("shot.hip")},
                         set(subject.request.paths))


class SeveralLibraryRowsTest(LibraryCase):

    def test_several_materials_read_every_file_they_own_once(self):
        model, section = self._material_section()
        metal, bricks = (model.find_asset_row_by_id(METAL), model.find_asset_row_by_id(BRICKS))
        tokens = self._textures("Metal", ("base.png",))
        model._assets[metal]._extra["textures"] = list(tokens)
        model._assets[bricks]._extra["textures"] = list(tokens)    # shared: read once
        subject = section.info_subject_for([_index(section, metal), _index(section, bricks)])
        self.assertEqual(("2 items selected", "", (("Items", "2"),), ()),
                         (subject.name, subject.type, subject.before, subject.after))
        wanted = (list(model.asset_files(METAL).values())
                  + [texstore.resolve(tokens[0], self.prefs)]
                  + list(model.asset_files(BRICKS).values()))
        self.assertEqual(file_info.Request(file_info.KIND_SIZES, tuple(wanted)), subject.request)


class KeysTest(LibraryCase):

    def test_keys_differ_between_rows_sections_and_selections(self):
        model, section = self._material_section()
        metal, bricks = (model.find_asset_row_by_id(METAL), model.find_asset_row_by_id(BRICKS))
        one = section.info_subject(_index(section, metal)).key
        self.assertNotEqual(one, section.info_subject(_index(section, bricks)).key)

        cops = cop_library.CopLibrary(self.prefs)
        cop_section = _section(node_section.CopSection, cops)
        row = cops._append_record(cops._asset_from_row({"id": METAL, "name": "Metal"}))
        self.assertNotEqual(one, cop_section.info_subject(_index(cop_section, row)).key,
                            "the same id in two sections has one key")

        pair = [_index(section, metal), _index(section, bricks)]
        both = section.info_subject_for(pair).key
        self.assertEqual(both, section.info_subject_for(list(reversed(pair))).key)
        third = [row for row in range(model.rowCount()) if row not in (metal, bricks)][0]
        self.assertNotEqual(both, section.info_subject_for(pair + [_index(section, third)]).key)


class OnlineTakesNoInfoTest(unittest.TestCase):

    def test_the_online_context_takes_no_info(self):
        self.assertTrue(section_base.Section.takes_info)
        self.assertFalse(online_section.OnlineContext.takes_info)
        online = online_section.OnlineContext.__new__(online_section.OnlineContext)
        self.assertIsNone(online.info_subject(QtCore.QModelIndex()))
        self.assertIsNone(online.info_subject_for([QtCore.QModelIndex()]))


if __name__ == "__main__":
    unittest.main()
