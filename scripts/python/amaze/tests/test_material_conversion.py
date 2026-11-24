"""Material conversion: one test per requirement in docs/requirements/material-conversion.md."""

import os
import shutil
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")    # BEFORE the app ▸p/first-app-picks-the-platform
from PySide6 import QtGui, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

from amaze import messages  # noqa: E402
from amaze.actions import materials as material_actions  # noqa: E402
from amaze.core import guard, library, library_db, library_files, locations, notes  # noqa: E402
from amaze.render import nodes  # noqa: E402
from amaze.render.material_conversion import engine, materialx  # noqa: E402
from amaze.render.material_conversion.report import ConversionReport  # noqa: E402
from amaze.tests import faults, test_support  # noqa: E402

TARGET = next((key for key in ("Redshift", "Octane") if test_support.renderer_loaded(key)), "")
needs_a_plugin = unittest.skipUnless(TARGET, "neither Redshift nor Octane is loaded")
BASE = (0.123, 0.456, 0.789)


def every_file(folder: str) -> dict:
    """Every folder and file under `folder`, a file with its bytes; backups keep what a save replaced."""
    found = {}
    for here, folders, names in os.walk(folder):
        relative = os.path.relpath(here, folder).replace(os.sep, "/") + "/"
        found.update((relative + name + "/", None) for name in folders)
        for name in names:
            with open(os.path.join(here, name), "rb") as handle:
                found[relative + name] = handle.read()
    return {path: data for path, data in found.items()
            if not path.startswith(("./" + guard.BACKUP_DIR + "/", guard.BACKUP_DIR + "/"))}


def textured(parent, texture: str):
    """A Karma material: a colour map, and a Karma-only ramp no other renderer takes."""
    builder = nodes.make_karma_builder(parent, "brick_source")
    shader = builder.createNode("mtlxstandard_surface")
    shader.parmTuple("base_color").set(BASE)
    image = builder.createNode("mtlximage")
    image.parm("signature").set("color3")
    image.parm("file").set(texture)
    shader.setNamedInput("base_color", image, 0)
    shader.setNamedInput("coat_color", builder.createNode("kma_rampconst", "karma_ramp"), 0)
    nodes.wire_builder_output(builder, shader)
    return builder


class _Reader(engine.RendererAPI):
    name = "Reader"

    def available(self):
        return True

    def to_materialx(self, container, builder, report):
        return builder.createNode("mtlxstandard_surface"), None


class _Writer(engine.RendererAPI):
    name = "Writer"

    def available(self):
        return True

    def from_materialx(self, container, parent, name, report):
        self.middle, self.fed = container, materialx.terminal_feed(container).type().name()
        written = parent.createNode("subnet", "written")
        return engine.Converted(written, written, False, report)    # wired False: renders black


class _Convert(unittest.TestCase):
    """A fixture library holding a saved, textured Karma material with a comment and a star."""

    @classmethod
    def setUpClass(cls):
        test_support.pin_env(test_support.class_scope(cls), "OCIO", "/dev/null")    # save_node asks

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.render_on_import = 0
        self.model = library.MaterialLibrary(preferences=self.prefs)
        scratch = tempfile.mkdtemp(prefix="amaze_convert_")
        self.addCleanup(shutil.rmtree, scratch, True)
        self.texture = os.path.join(scratch, "brick_albedo.png")
        picture = QtGui.QImage(16, 16, QtGui.QImage.Format.Format_RGB888)
        picture.fill(QtGui.QColor("#a0522d"))
        self.assertTrue(picture.save(self.texture))
        self.source = self.saved()
        self.model.toggle_fav(self.row(self.source))
        notes.set_note(self.prefs, self.note_key(self.source), [{"t": "text", "text": "keep"}])
        library_db.flush(self.prefs)

    def saved(self):
        builder = textured(hou.node("/mat"), self.texture)
        self.addCleanup(test_support.drop_node, builder)
        held = test_support.asset_ids(self.model)
        self.assertEqual("Karma", material_actions.add_asset(
            self.model, builder, "Bricks", "rough,red", False, name="Brick Wall", license="CC0"))
        return test_support.arrived(self.model, held)[0]

    def row(self, asset) -> int:
        return self.model.find_asset_row_by_id(asset.mat_id)

    def folder(self, asset) -> str:
        return self.model.asset_directories(asset.mat_id)["folder"]

    def note_key(self, asset) -> str:
        return notes.note_key("material", asset.mat_id)

    def convert(self, target: str = ""):
        """Convert the source: (ok, report, the rows it added)."""
        held = test_support.asset_ids(self.model)
        ok, report = material_actions.convert(
            self.model, self.model.index(self.row(self.source), 0), target or TARGET)
        return ok, report, test_support.arrived(self.model, held)

    def as_stored(self) -> dict:
        """The source as the library holds it: its row on disk, its files, its comment."""
        stored = guard.Guard(self.prefs.dir).read(library_files.MATERIALS).document
        return {"row": stored["assets"][str(self.source.mat_id)],
                "files": every_file(self.folder(self.source)),
                "comment": notes.note_for(self.prefs, self.note_key(self.source))}


@needs_a_plugin
class ConvertTest(_Convert):

    def test_mc01_converting_never_changes_the_source(self):
        before = self.as_stored()
        self.assertTrue(self.convert()[0])
        with test_support.full_disk_for(os.path.join(self.prefs.dir, library_files.MATERIALS)):
            self.assertFalse(self.convert()[0])
        held = library_db.guard_of(self.prefs)
        counting = held.disk = faults.FaultDisk()
        self.convert()
        for step in range(1, counting.steps + 1):    # a crash at each step, the write torn
            held.disk = faults.FaultDisk(cut_at=step, torn=True)
            try:
                self.convert()
            except faults.Cut:
                pass
            held.disk = guard.Disk()
            with self.subTest(step=step):
                self.assertEqual(before, self.as_stored())

    def test_mc02_a_conversion_that_fails_adds_nothing(self):
        real_save = nodes.NodeHandler.save_node

        def saved_then_failed(handler, *args, **kwargs):
            real_save(handler, *args, **kwargs)    # the network and the texture copy are staged
            raise OSError("the disk went away")

        failures = {
            "no copy built": mock.patch.object(engine, "convert", return_value=engine.Converted(
                None, None, False, ConversionReport("x"))),
            "the save raised": mock.patch.object(nodes.NodeHandler, "save_node", saved_then_failed),
            "the database is full": test_support.full_disk_for(
                os.path.join(self.prefs.dir, library_files.MATERIALS)),
            "every write fails": mock.patch.object(library_db.guard_of(self.prefs), "disk",
                                                   faults.FaultDisk(full_from=1)),
        }
        before, rows = every_file(self.prefs.dir), test_support.asset_ids(self.model)
        for why, failing in failures.items():
            with self.subTest(failure=why):
                with failing:
                    try:
                        ok, _report, added = self.convert()
                    except OSError:
                        ok, added = False, test_support.arrived(self.model, rows)
                self.assertFalse(ok)
                self.assertEqual([], added)
                self.assertEqual(before, every_file(self.prefs.dir))

    def test_mc10_the_copy_is_a_new_material_with_its_own_folder(self):
        folders = {asset.mat_id: self.model.asset_directories(asset.mat_id).get("folder")
                   for asset in self.model.assets}
        others = {mat_id: every_file(folder) for mat_id, folder in folders.items() if folder}
        ok, _report, added = self.convert()
        self.assertTrue(ok)
        copy, = added
        self.assertNotIn(copy.mat_id, folders)
        self.assertNotIn(self.folder(copy), folders.values())
        self.assertTrue(os.path.isfile(os.path.join(self.folder(copy), copy.mat_id + self.prefs.ext)))
        self.assertEqual(others, {mat_id: every_file(folders[mat_id]) for mat_id in others})

    def test_mc11_converting_leaves_the_scene_and_its_undo_list_as_they_were(self):
        self.assertTrue(hou.undos.areEnabled(), "premise: this Houdini records undo")

        def scene():
            return sorted(node.path() for node in hou.node("/").allSubChildren())

        before, undo = scene(), hou.undos.undoLabels()
        self.assertTrue(self.convert()[0])
        with mock.patch.object(engine, "convert", side_effect=RuntimeError("the converter broke")):
            with self.assertRaises(RuntimeError):
                self.convert()
        self.assertEqual(before, scene(), "a scratch network was left in the scene")
        self.assertEqual(undo, hou.undos.undoLabels(), "the conversion is on the undo list")

    def test_mc22_the_copy_is_the_target_renderers_own_builder(self):
        copy, = self.convert()[2]
        handler = nodes.NodeHandler(self.prefs)
        self.assertEqual(TARGET, copy.renderer)
        self.assertEqual({"mat", "lop"}, handler.import_targets(copy))
        ok, reason, made = handler.import_asset_to_scene(copy, target="mat")
        self.assertTrue(ok, reason)
        self.addCleanup(test_support.drop_node, made[0])
        self.assertEqual(TARGET, handler.get_renderer_from_node(made[0]))
        stage = hou.node("/obj").createNode("lopnet", "convert_probe")
        self.addCleanup(test_support.drop_node, stage)
        shelf = stage.createNode("materiallibrary")
        ok, reason, _made = handler.import_asset_to_scene(copy, target="lop", context_node=shelf)
        self.assertTrue(ok, reason)
        self.assertTrue([prim for prim in shelf.stage().Traverse() if prim.GetTypeName() == "Material"])

    def test_mc23_the_copys_surface_is_wired_or_the_report_says_it_renders_black(self):
        with material_actions.rebuilt_as(self.prefs, self.source, TARGET, ConversionReport("x")) as made:
            self.assertTrue(made.wired and nodes.surface_terminal_wired(made.builder))
        registry = {engine.INTERMEDIATE: engine.apis()[engine.INTERMEDIATE],
                    "Reader": _Reader(), "Writer": _Writer()}
        scratch = hou.node("/obj").createNode("matnet")
        self.addCleanup(test_support.drop_node, scratch)
        with mock.patch.dict(engine._registry, registry, clear=True):
            made = engine.convert(scratch, "Reader", "Writer", scratch, "Unwired")
        self.assertEqual([engine.UNWIRED], made.report.skipped)

    def test_mc24_the_copy_uses_its_own_copies_of_the_textures(self):
        copy, = self.convert()[2]
        own, theirs = self.model.texture_paths(copy), self.model.texture_paths(self.source)
        self.assertEqual(1, len(own))
        self.assertTrue(own[0].startswith(self.folder(copy) + os.sep), own)
        with open(own[0], "rb") as mine, open(theirs[0], "rb") as source:
            self.assertEqual(source.read(), mine.read())

    def test_mc25_the_copy_keeps_name_categories_tags_and_licence_only(self):
        copy, = self.convert()[2]
        self.assertEqual(("Brick Wall", ["Bricks"], ["rough", "red"], "CC0"),
                         (copy.name, list(copy.categories), list(copy.tags), copy.license))
        self.assertTrue(locations.is_favourite(self.prefs, self.source.mat_id, self.model.DB_FILENAME))
        self.assertFalse(locations.is_favourite(self.prefs, copy.mat_id, self.model.DB_FILENAME))
        self.assertEqual({}, notes.note_for(self.prefs, self.note_key(copy)))

    def test_mc26_what_the_conversion_leaves_out_is_named_in_its_report(self):
        _ok, report, _added = self.convert()
        self.assertTrue([line for line in report.skipped + report.approximated if "karma_ramp" in line],
                        report.summary_lines())

    def test_mc27_one_message_for_the_selection_and_a_failure_stops_nothing(self):
        second, real = self.saved(), material_actions.convert

        def crashing_on_the_first(model, index, *args, **kwargs):
            if model.assets[index.row()].mat_id == self.source.mat_id:
                raise RuntimeError("boom")
            return real(model, index, *args, **kwargs)

        held = test_support.asset_ids(self.model)
        with mock.patch.object(material_actions, "convert", crashing_on_the_first):
            message, details, complete, _unlisted = material_actions.convert_rows(
                self.model, [self.source.mat_id, second.mat_id, "gone"], TARGET)
        self.assertEqual(messages.CONVERSION_SUMMARY % (1, 2, "MaterialX", TARGET), message)
        self.assertFalse(complete)
        self.assertIn(messages.CONVERSION_CRASHED_LINE % ("Brick Wall", "boom"), details)
        self.assertEqual(1, len(test_support.arrived(self.model, held)), "the second was not converted")


class RouteTest(_Convert):

    def test_mc20_a_material_is_converted_only_when_it_can_be(self):
        with mock.patch.object(nodes.NodeHandler, "rebuild_saved",
                               side_effect=AssertionError("built before the reason")):
            with test_support.plugins_loaded():
                ok, report, added = self.convert("Octane")
            self.assertEqual((False, []), (ok, added))
            self.assertEqual(["Octane isn't loaded in this Houdini, so the conversion can't run"],
                             report.skipped)
            ok, report, added = self.convert("Karma")
        self.assertEqual((False, [], ["the material is already MaterialX"]),
                         (ok, added, report.skipped))

    def test_mc21_every_renderer_converts_to_every_other_through_materialx(self):
        with test_support.plugins_loaded(*engine.targets()):
            for source in engine.targets():
                for target in engine.targets():
                    with self.subTest(source=source, target=target):
                        self.assertEqual(source != target, engine.can_convert(source, target))
        writer = _Writer()
        registry = {engine.INTERMEDIATE: engine.apis()[engine.INTERMEDIATE],
                    "Reader": _Reader(), "Writer": writer}
        scratch = hou.node("/obj").createNode("matnet")
        self.addCleanup(test_support.drop_node, scratch)
        with mock.patch.dict(engine._registry, registry, clear=True):
            engine.convert(scratch, "Reader", "Writer", scratch, "Through")
        self.assertEqual("mtlxstandard_surface", writer.fed, "the writer was not given MaterialX")
        with self.assertRaises(hou.ObjectWasDeleted):
            writer.middle.path()    # the MaterialX step is removed


if __name__ == "__main__":
    unittest.main()
