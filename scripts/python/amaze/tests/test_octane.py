"""Octane 2026.6 materials built for real; plugin cases skip where Octane is absent."""

import math
import os
import shutil
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze import preview  # noqa: E402
from amaze.actions import materials as material_actions  # noqa: E402
from amaze.core import material_files  # noqa: E402
from amaze.core import library as library_mod  # noqa: E402
from amaze.core import material, renderers  # noqa: E402
from amaze.prefs import persistence  # noqa: E402
from amaze.prefs import prefs as prefs_mod  # noqa: E402
from amaze.render import material_converter  # noqa: E402
from amaze.render import nodes  # noqa: E402
from amaze.render.material_conversion import octane as octane_api  # noqa: E402
from amaze.tests import test_support  # noqa: E402

OCTANE_SHADER = "octane::NT_MAT_STANDARD_SURFACE"
RED = (0.8, 0.05, 0.05)


def _octane_builder(parent):
    """Octane's own builder, made by Octane's own factory."""
    import octane_material_builder
    return octane_material_builder.createMaskedOctaneSubnet(target_node=parent)


def _shader(builder):
    return next(c for c in builder.children() if c.type().name() == OCTANE_SHADER)


def _menu_label(parm):
    return dict(zip(parm.menuItems(), parm.menuLabels())).get(parm.evalAsString())


def _a_viewer_octane_offers():
    """The LAST display and view Octane lists under this OCIO config, so the default cannot pass."""
    net = hou.node("/obj").createNode("matnet")
    try:
        labels = [label for label in net.createNode("octane_mat_renderTarget")
                  .parm("ocioViewMenu").menuLabels() if ": " in label]
    finally:
        net.destroy()
    display, view = labels[-1].split(": ", 1)
    return {"display": display, "view": view, "space": "ACEScg"}


def _write_mat(prefs, asset_id, text):
    path = material.payload_path(prefs, asset_id, prefs.ext)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="latin-1") as handle:
        handle.write(text)


class TheTileNamesAnOctaneShader(unittest.TestCase):
    """The shader type is read off the saved .mat's type lines; no plugin needed."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.prefs = test_support.fixture_prefs(self)

    def _label(self, renderer, *types):
        asset = material.Material(name="label_probe", renderer=renderer,
                                  mat_id="label_probe_%s" % renderer)
        _write_mat(self.prefs, asset.mat_id,
                   "".join("type = %s\n" % name for name in types))
        return material_files.get_shader_type_label(self.prefs, asset)

    def test_the_label_follows_the_type_lines_and_the_renderers_table(self):
        for renderer, types, label in (
                ("Octane", (OCTANE_SHADER,), "Standard Surface"),
                ("Octane", (OCTANE_SHADER, "octane::NT_MAT_MIX", OCTANE_SHADER), "Mix"),
                ("Octane", ("octane::NT_MAT_DIFFUSE_LAYER", "octane::NT_MAT_LAYER"),
                 "Layered"),    # NT_MAT_DIFFUSE is a prefix of the layer type: the order decides
                ("Octane", ("mtlximage", "mtlxstandard_surface"), "MaterialX"),
                ("Redshift", ("redshift::OpenPBRMaterial",), "PBR"),
                ("Redshift", (OCTANE_SHADER,), "")):
            with self.subTest(renderer=renderer, label=label):
                self.assertEqual(label, self._label(renderer, *types))

    def test_the_library_reads_the_label_for_octane(self):
        asset = material.Material(name="label_probe", renderer="Octane",
                                  mat_id="label_probe_library")
        _write_mat(self.prefs, asset.mat_id, "type = %s\n" % OCTANE_SHADER)
        model = library_mod.MaterialLibrary(preferences=self.prefs)
        self.assertEqual("Octane:Standard Surface", model.renderer_label(asset))


class TheOctaneSamplesSetting(unittest.TestCase):
    """Its own dial, like Karma's: Octane's path tracing counts samples on its own scale."""

    def test_it_is_a_shared_setting_with_its_default_clamped_to_its_row(self):
        self.assertEqual(
            ("octane_rendersamples", "_octane_rendersamples", 256),
            persistence.SHARED_KEYS.get("octane_rendersamples"))
        p = prefs_mod.Prefs()
        self.assertEqual(256, p.octane_rendersamples)
        low, high = renderers.OCTANE.samples_range
        p.octane_rendersamples = high + 500
        self.assertEqual(high, p.octane_rendersamples)
        p.octane_rendersamples = 0
        self.assertEqual(low, p.octane_rendersamples)


class TheOctaneCheckFollowsTheHost(unittest.TestCase):
    """Both polarities, so a green cannot mean `always True`."""

    def test_it_agrees_with_the_type_registry_and_reads_an_empty_one_as_absent(self):
        registered = hou.vopNodeTypeCategory().nodeType(OCTANE_SHADER) is not None
        self.assertEqual(registered, material_converter._octane_type_available())
        with mock.patch.object(hou, "nodeTypeCategories", lambda: {}):
            self.assertFalse(material_converter._octane_type_available())


class WhatOctaneIgnoresIsJudgedByTheReadersDefaultTest(unittest.TestCase):
    """`report_ignored` names an input only once it is off its default; no plugin needed."""

    def test_a_moved_input_is_named_and_a_default_one_is_not(self):
        from amaze.render.material_conversion import octane_reader
        from amaze.render.material_conversion.report import ConversionReport
        parent = hou.node("/obj").createNode("matnet")
        self.addCleanup(parent.destroy)
        builder = nodes.make_karma_builder(parent, "ignored_probe")
        shader = builder.createNode("mtlxstandard_surface")
        image = builder.createNode("mtlximage")
        shader.setNamedInput("base_color", image, 0)
        quiet = ConversionReport("quiet")
        octane_api.report_ignored(builder, quiet)
        self.assertEqual([], quiet.skipped)
        image.parm("filtertype").set("closest")
        said = ConversionReport("said")
        octane_api.report_ignored(builder, said)
        self.assertEqual(1, len([line for line in said.skipped if "filtertype" in line]),
                         said.skipped)
        self.assertFalse(octane_reader.at_default(image, "filtertype"))
        self.assertTrue(octane_reader.at_default(image, "no_such_parm"), "a parm it lacks")


@unittest.skipUnless(test_support.renderer_loaded("Octane"), "the Octane plugin is not loaded")
class OctanesOwnBuilderIsAnOctaneMaterial(unittest.TestCase):
    """Recognised by Octane's own marker, before any MaterialX walk."""

    def setUp(self):
        self.builder = _octane_builder(hou.node("/mat"))
        self.addCleanup(self.builder.destroy)

    def _renderer(self, node):
        return nodes.NodeHandler(None).get_renderer_from_node(node)

    def test_the_marker_decides_and_materialx_inside_does_not(self):
        """The other polarity: a MaterialX subnet stays Karma, a markless one stays refused."""
        self.assertEqual("Octane", self._renderer(self.builder))
        image = self.builder.createNode("mtlximage")
        _shader(self.builder).setNamedInput("baseColor", image, 0)
        self.assertEqual("Octane", self._renderer(self.builder))
        bare = _octane_builder(hou.node("/mat"))
        self.addCleanup(bare.destroy)
        bare.destroyUserData(nodes.OCTANE_BUILDER_MARK)
        self.assertEqual("", self._renderer(bare))
        bare.createNode("mtlxstandard_surface")
        self.assertEqual("Karma", self._renderer(bare))


@unittest.skipUnless(test_support.renderer_loaded("Octane"), "the Octane plugin is not loaded")
class OctanesOwnBuilderRoundTrips(unittest.TestCase):
    """Saved whole, as a MaterialX builder is, so it comes back as Octane's builder."""

    @classmethod
    def setUpClass(cls):
        test_support.pin_env(test_support.class_scope(cls), "OCIO", "/dev/null")    # save_node gates on $OCIO; nothing renders here

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.render_on_import = 0
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        self.mat = hou.node("/mat")
        self.before = {n.path() for n in self.mat.children()}
        self.addCleanup(self._clear_mat)

    def _clear_mat(self):
        for child in self.mat.children():
            if child.path() not in self.before:
                try:
                    child.destroy()
                except hou.Error:
                    pass

    def _saved(self, node):
        held = test_support.asset_ids(self.model)
        renderer = material_actions.add_asset(self.model, node, "OctaneProbe", "", False)
        self.assertEqual("Octane", renderer, "the save did not take it as Octane")
        saved, = test_support.arrived(self.model, held)
        return saved

    def _imported(self, asset, target="mat", context=None):
        ok, reason, created = nodes.NodeHandler(self.prefs).import_asset_to_scene(
            asset, target=target, context_node=context)
        self.assertTrue(ok, reason)
        return created[0]

    def test_it_comes_back_as_octanes_builder(self):
        source = _octane_builder(self.mat)
        _shader(source).parmTuple("baseColor").set(RED)
        asset = self._saved(source)
        self.assertEqual("Octane:Standard Surface", self.model.renderer_label(asset))
        self.assertEqual("subnet", material_files.get_saved_node_type(self.prefs, asset))
        imported = self._imported(asset)
        self.assertEqual("1", imported.userData(nodes.OCTANE_BUILDER_MARK),
                         "the import lost Octane's marker")
        self.assertEqual(
            [], [c.name() for c in imported.children()
                 if c.userData(nodes.OCTANE_BUILDER_MARK)],
            "the builder came back nested inside another subnet")
        self.assertTrue(nodes.surface_terminal_wired(imported))
        for got, want in zip(_shader(imported).parmTuple("baseColor").eval(), RED):
            self.assertAlmostEqual(want, got, places=5)
        self.assertEqual("Octane", nodes.NodeHandler(
            self.prefs).get_renderer_from_node(imported),
            "an imported Octane builder cannot be saved again")

    def test_it_goes_into_a_material_library(self):
        asset = self._saved(_octane_builder(self.mat))
        self.assertEqual({"mat", "lop"},
                         nodes.NodeHandler(self.prefs).import_targets(asset))
        stage = hou.node("/obj").createNode("lopnet", "octane_lop_probe")
        self.addCleanup(stage.destroy)
        imported = self._imported(asset, target="lop", context=stage)
        library = imported.parent()
        self.assertEqual("materiallibrary", library.type().name())
        from pxr import UsdShade
        outputs = [o.GetFullName()
                   for prim in library.stage().Traverse()
                   if prim.GetTypeName() == "Material"
                   for o in UsdShade.Material(prim).GetOutputs()]
        self.assertIn("outputs:Octane:surface", outputs)

    def test_the_classic_container_keeps_its_shape(self):
        """`octane_vopnet` still saves its contents and rebuilds by type in /mat."""
        asset = self._saved(self.mat.createNode("octane_vopnet"))
        self.assertEqual("octane_vopnet", material_files.get_saved_node_type(self.prefs, asset))
        self.assertEqual("octane_vopnet", self._imported(asset).type().name())
        self.assertEqual("Octane:Standard Surface", self.model.renderer_label(asset))

    def test_the_classic_container_is_rebuilt_on_its_way_into_solaris(self):
        """Copy To /stage: the classic one becomes the Solaris builder, its shader kept."""
        classic = self.mat.createNode("octane_vopnet")
        classic.node("Standard_Surface").parmTuple("baseColor").set(RED)
        asset = self._saved(classic)
        self.assertEqual({"mat", "lop"}, nodes.NodeHandler(self.prefs).import_targets(asset))
        stage = hou.node("/obj").createNode("lopnet", "octane_classic_probe")
        self.addCleanup(stage.destroy)
        imported = self._imported(asset, target="lop", context=stage)
        self.assertEqual(octane_api.SOLARIS_CONTAINER, imported.type().name())
        for got, want in zip(octane_api.find_shader(imported).parmTuple("baseColor").eval(), RED):
            self.assertAlmostEqual(want, got, places=5)
        from pxr import UsdShade
        outputs = [o.GetFullName()
                   for prim in imported.parent().stage().Traverse()
                   if prim.GetTypeName() == "Material"
                   for o in UsdShade.Material(prim).GetOutputs()]
        self.assertIn("outputs:Octane:surface", outputs)

    def test_the_solaris_container_reads_as_usd(self):
        asset = self._saved(self.mat.createNode("octane_solaris_material_builder"))
        self.assertEqual({"mat", "lop"},
                         nodes.NodeHandler(self.prefs).import_targets(asset))
        self.assertEqual("USD Octane:Standard Surface", self.model.renderer_label(asset))


@unittest.skipUnless(test_support.renderer_loaded("Octane"), "the Octane plugin is not loaded")
class TheOctaneThumbnailIsTheMaterialXStage(unittest.TestCase):
    """The MaterialX thumbnail's USD stage with Octane's settings; nothing renders."""

    def setUp(self):
        patcher = mock.patch.object(preview.thumbnail_scene, "ocio_from_viewer",
                                    lambda: dict(_a_viewer_octane_offers()))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.octane_rendersamples = 77    # not 256: the default proves nothing
        self.scaffold = preview.build_usd_scaffold(self.prefs, "Octane")
        self.assertIsNotNone(self.scaffold, "no scaffold with the OCIO seam patched")
        self.addCleanup(test_support.drop_node, self.scaffold["net"])
        self.settings = self.scaffold["render_props"]

    def test_the_stage_carries_octanes_settings(self):
        settings = self.settings
        with self.subTest("rendered through Octane's own delegate"):
            self.assertTrue(settings.type().name().startswith("otoy::Octane"))
            self.assertEqual("HdOctaneRendererPlugin",
                             self.scaffold["rop"].parm("renderer").evalAsString())
        with self.subTest("path traced under the stage's own lights"):
            self.assertEqual("NT_KERN_PATHTRACING",
                             settings.parm("xn__octaneglobalParmKernel_wcbg").evalAsString())
            self.assertEqual("Dome Light", _menu_label(
                settings.parm("xn__octaneglobalParmEnvironment_1kbg")))
        with self.subTest("the samples setting caps path tracing"):
            cap = preview.usd_scene.OCTANE_PATH_TRACING_CAP
            self.assertIn("pathtracing",
                          settings.parmTemplateGroup().containingFolder(cap).name(),
                          "the cap written is another kernel's")
            self.assertEqual(77, settings.parm(cap).eval())
        with self.subTest("an ACEScg picture the size of the tile"):
            self.assertEqual("ACEScg", settings.parm(
                "xn__octaneglobalociocolorspace_fjbg").evalAsString())
            self.assertEqual((self.prefs.rendersize,) * 2,
                             tuple(settings.parmTuple("resolution").eval()))
        with self.subTest("a floor picture Octane reads"):    # no `.rat`: the floor rendered black from one
            image = next(c for c in self.scaffold["lib1"].children()
                         if c.type().name() == "mtlxtiledimage")
            self.assertTrue(image.parm("file").unexpandedString().endswith(".exr"))
        with self.subTest("no depth of field, its lights scaled"):    # ▸r/octane-thumbnail
            stage = self._stage_above_the_floor(self.scaffold)
            camera = stage.GetPrimAtPath(preview.usd_scene.RENDER_CAMERA)
            self.assertEqual(0.0, camera.GetAttribute("fStop").Get())
            right = stage.GetPrimAtPath("/shaderBallScene/lights/Right")
            self.assertAlmostEqual(math.pi * preview.usd_scene.OCTANE_LIGHT_SCALE,
                                   right.GetAttribute("inputs:intensity").Get(), places=4)

    def _stage_above_the_floor(self, scaffold):
        upstream = scaffold["lib1"].inputs()[0]
        upstream.cook(force=True)
        return upstream.stage()

    def test_karmas_stage_is_left_as_it_was(self):
        """The other polarity: the edit and the EXR floor are Octane's alone."""
        karma = preview.build_usd_scaffold(self.prefs, "Karma")
        self.addCleanup(test_support.drop_node, karma["net"])
        self.assertEqual("reference::2.0", karma["lib1"].inputs()[0].type().name())
        stage = self._stage_above_the_floor(karma)
        self.assertAlmostEqual(5.6, stage.GetPrimAtPath(preview.usd_scene.RENDER_CAMERA)
                               .GetAttribute("fStop").Get(), places=4)
        image = next(c for c in karma["lib1"].children()
                     if c.type().name() == "mtlxtiledimage")
        self.assertTrue(image.parm("file").unexpandedString().endswith(".rat"))

    def _batch_material(self, node):
        """The material prim the batch USD holds for `node`, and its outputs."""
        from pxr import Usd, UsdShade
        folder = test_support.scratch_dir("amaze_octane_thumb_")
        self.addCleanup(shutil.rmtree, folder, True)
        batch = preview.write_batch(self.scaffold, [("PROBE", node)], folder)
        prim = batch["prims"][0]
        stage = Usd.Stage.Open(batch["usd"])
        outputs = [o.GetFullName()
                   for o in UsdShade.Material(stage.GetPrimAtPath(prim)).GetOutputs()]
        return prim, outputs

    def test_each_container_is_an_octane_material_in_the_batch(self):
        mat = hou.node("/mat")
        for kind in ("builder", "octane_solaris_material_builder", "octane_vopnet"):
            with self.subTest(container=kind):
                node = (_octane_builder(mat) if kind == "builder"
                        else mat.createNode(kind))
                self.addCleanup(test_support.drop_node, node)
                prim, outputs = self._batch_material(node)
                self.assertTrue(prim.startswith("/materials/"), prim)
                self.assertTrue(any(o.endswith(":surface") and ":mtlx:" not in o
                                    for o in outputs), outputs)

    def test_a_classic_container_keeps_its_own_shader(self):
        vopnet = hou.node("/mat").createNode("octane_vopnet")
        self.addCleanup(test_support.drop_node, vopnet)
        vopnet.node("Standard_Surface").parmTuple("baseColor").set(RED)
        lib = self.scaffold["net"].createNode("materiallibrary")
        rebuilt = octane_api.classic_into(lib, vopnet)
        fed = rebuilt.node("octane_material").input(0)
        self.assertIsNotNone(fed, "nothing feeds the rebuilt material")
        self.assertEqual("Standard_Surface", fed.name())
        for got, want in zip(fed.parmTuple("baseColor").eval(), RED):
            self.assertAlmostEqual(want, got, places=5)
        self.assertEqual(1, len([c for c in rebuilt.children()
                                 if c.type().name() == OCTANE_SHADER]),
                         "the Solaris builder's own shader was left beside the classic one")


if __name__ == "__main__":
    unittest.main()
