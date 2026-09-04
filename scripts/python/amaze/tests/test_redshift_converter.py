"""Karma -> Redshift: the mirror of Convert to Karma. A saved Karma material's MaterialX network becomes a Redshift material builder whose shader carries the same numbers, whose textures are the SAME files, and whose terminal is wired. ▸r/redshift-nodes"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import material  # noqa: E402
from amaze.render import nodes  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401 - redirects the log


def _redshift_available():
    try:
        return hou.vopNodeTypeCategory().nodeType("redshift_vopnet") is not None
    except Exception:                                        # noqa: BLE001
        return False


SPEC = {    # distinctive values, so a default reappearing cannot pass as a copy
    "base_color": (0.123, 0.456, 0.789),
    "specular_roughness": 0.321,
    "metalness": 0.25,
    "specular_IOR": 1.77,
    "coat": 0.4,
    "emission_color": (0.9, 0.1, 0.2),
}
ALBEDO = "$AMAZELIB/matX/Test__pkg/textures/test_albedo.png"
ROUGH = "$AMAZELIB/matX/Test__pkg/textures/test_rough.png"
NORMAL = "$AMAZELIB/matX/Test__pkg/textures/test_normal.png"


def _karma_material(parent, name="karma_source"):
    """A real Karma material through the real engine: a standard surface with a colour map, a roughness map through the UV chain, and a normal map."""
    def produce(builder):
        shader = builder.createNode("mtlxstandard_surface")
        for parm, value in SPEC.items():
            if isinstance(value, tuple):
                shader.parmTuple(parm).set(value)
            else:
                shader.parm(parm).set(value)
        texcoord = builder.createNode("mtlxtexcoord")
        scale = builder.createNode("mtlxmultiply")
        scale.parm("signature").set("vector2")
        scale.setNamedInput("in1", texcoord, 0)
        scale.parmTuple("in2_vector2").set((2.0, 3.0))
        albedo = builder.createNode("mtlximage")
        albedo.parm("signature").set("color3")
        albedo.parm("file").set(ALBEDO)
        albedo.parm("filecolorspace").set("srgb_texture")
        albedo.setNamedInput("texcoord", scale, 0)
        shader.setNamedInput("base_color", albedo, 0)
        rough = builder.createNode("mtlximage")
        rough.parm("signature").set("default")
        rough.parm("file").set(ROUGH)
        rough.parm("filecolorspace").set("Raw")
        shader.setNamedInput("specular_roughness", rough, 0)
        normal_img = builder.createNode("mtlximage")
        normal_img.parm("signature").set("vector3")
        normal_img.parm("file").set(NORMAL)
        normalmap = builder.createNode("mtlxnormalmap")
        normalmap.parm("scale").set(0.75)
        normalmap.setNamedInput("in", normal_img, 0)
        shader.setNamedInput("normal", normalmap, 0)
        return shader
    return nodes.build_karma_material(parent, name, produce).builder


@unittest.skipUnless(_redshift_available(),
                     "the Redshift plugin is not loaded")
class AKarmaMaterialBecomesARedshiftOne(unittest.TestCase):
    """Network to network, through the engine door the library will call."""

    @classmethod
    def setUpClass(cls):
        from amaze.render import redshift_converter
        cls.converter = redshift_converter
        cls.parent = hou.node("/mat") or hou.node("/").createNode("mat")
        cls.source = _karma_material(cls.parent)
        cls.result = redshift_converter.convert_karma_builder(
            cls.source, cls.parent, "converted")
        cls.builder, cls.shader, cls.wired, cls.report = cls.result

    @classmethod
    def tearDownClass(cls):
        for node in (cls.source, cls.builder):
            if node is not None:
                try:
                    node.destroy()
                except hou.ObjectWasDeleted:
                    pass

    def _children(self, type_name):
        return [c for c in self.builder.children()
                if c.type().name() == type_name]

    def _inputs(self, node):
        return {c.outputName(): c.inputNode() for c in node.inputConnections()}    # `outputName` is the DESTINATION's input connector; `inputName` names the source's output, `out` on every VOP ▸r/node-connection-names

    def test_the_container_is_a_redshift_builder_the_library_reads_as_redshift(self):
        self.assertEqual("rs_usd_material_builder", self.builder.type().name())    # Redshift's Solaris container, so the twin can be copied into a LOP material library as well as /mat
        handler = nodes.NodeHandler.__new__(nodes.NodeHandler)
        self.assertEqual("Redshift", handler.get_renderer_from_node(self.builder))

    def test_the_shader_is_a_standard_material_wired_to_a_usd_terminal(self):
        self.assertEqual("redshift::StandardMaterial", self.shader.type().name())
        self.assertTrue(self.wired, "the terminal is not wired")
        terminals = [c for c in self.builder.children()
                     if c.type().name() in material.REDSHIFT_TERMINALS]
        self.assertEqual(["redshift_usd_material"],
                         [t.type().name() for t in terminals],
                         "one USD terminal, which works in /mat and Solaris")
        surface = material.terminal_input(self._inputs(terminals[0]), "surface")
        self.assertIsNotNone(surface)
        self.assertEqual(self.shader.path(), surface.path())

    def test_the_numbers_cross_over(self):
        s = self.shader
        self.assertEqual(SPEC["base_color"], tuple(round(v, 3) for v in s.parmTuple("base_color").eval()))
        self.assertAlmostEqual(SPEC["specular_roughness"], s.parm("refl_roughness").eval(), places=5)
        self.assertAlmostEqual(SPEC["metalness"], s.parm("metalness").eval(), places=5)
        self.assertAlmostEqual(SPEC["specular_IOR"], s.parm("refl_ior").eval(), places=5)
        self.assertAlmostEqual(SPEC["coat"], s.parm("coat_weight").eval(), places=5)
        self.assertEqual(SPEC["emission_color"], tuple(round(v, 3) for v in s.parmTuple("emission_color").eval()))

    def test_the_textures_are_the_same_files_in_the_right_colour_space(self):
        samplers = {t.parm("tex0").unexpandedString(): t
                    for t in self._children("redshift::TextureSampler")}
        self.assertIn(ALBEDO, samplers, "the colour map did not cross over as the SAME file")
        self.assertIn(ROUGH, samplers, "the roughness map did not cross over")
        self.assertEqual("sRGB", samplers[ALBEDO].parm("tex0_colorSpace").evalAsString())
        self.assertEqual("Raw", samplers[ROUGH].parm("tex0_colorSpace").evalAsString())
        inputs = self._inputs(self.shader)
        self.assertEqual(samplers[ALBEDO].path(), inputs["base_color"].path())
        self.assertEqual(samplers[ROUGH].path(), inputs["refl_roughness"].path())

    def test_the_uv_scale_rides_the_sampler(self):
        sampler = next(t for t in self._children("redshift::TextureSampler")
                       if t.parm("tex0").unexpandedString() == ALBEDO)
        self.assertEqual((2.0, 3.0), tuple(sampler.parmTuple("scale").eval()))

    def test_the_normal_map_is_a_tangent_space_bump_on_the_shader(self):
        bumps = self._children("redshift::BumpMap")
        self.assertEqual(1, len(bumps))
        bump = bumps[0]
        self.assertEqual("1", bump.parm("inputType").evalAsString(), "not tangent-space")
        self.assertAlmostEqual(0.75, bump.parm("scale").eval(), places=5)
        fed = self._inputs(bump)["input"]
        self.assertEqual("redshift::TextureSampler", fed.type().name())
        self.assertEqual(NORMAL, fed.parm("tex0").unexpandedString())
        self.assertEqual("Raw", fed.parm("tex0_colorSpace").evalAsString())
        self.assertEqual(bump.path(), self._inputs(self.shader)["bump_input"].path())

    def test_the_report_names_nothing_skipped_for_this_network(self):
        self.assertEqual([], self.report.skipped, self.report.summary_lines())


@unittest.skipUnless(_redshift_available(),
                     "the Redshift plugin is not loaded")
class WhatHasNoRedshiftShapeIsReportedNotInvented(unittest.TestCase):

    def test_an_unknown_upstream_node_is_named_in_the_report(self):
        from amaze.render import redshift_converter
        parent = hou.node("/mat") or hou.node("/").createNode("mat")

        def produce(builder):
            shader = builder.createNode("mtlxstandard_surface")
            noise = builder.createNode("mtlxfractal3d")
            shader.setNamedInput("base_color", noise, 0)
            return shader
        source = nodes.build_karma_material(parent, "noisy", produce).builder
        self.addCleanup(source.destroy)
        builder, shader, wired, report = redshift_converter.convert_karma_builder(
            source, parent, "noisy_rs")
        self.addCleanup(builder.destroy)
        self.assertTrue(wired)
        self.assertTrue(any("mtlxfractal3d" in line for line in report.skipped),
                        "the unconvertible noise was not reported: %r" % (report.skipped,))
        self.assertNotIn("base_color", {c.inputName() for c in shader.inputConnections()},
                         "something was wired into base_color in place of the noise")


@unittest.skipUnless(_redshift_available(),
                     "the Redshift plugin is not loaded")
class AConstantOnAWireLandsAsAValue(unittest.TestCase):
    """Downloaded materials expose their dials as mtlxconstant nodes WIRED into inputs (a Tint into the colour multiply, a UV scale into the texcoord multiply). Redshift's math nodes default to zero, so a dropped constant renders black - one twin did, 2026-09-04. ▸r/redshift-nodes"""

    TINT = (0.5, 0.25, 1.0)
    UV = 5.0
    ROUGH = 0.3

    @classmethod
    def setUpClass(cls):
        from amaze.render import redshift_converter
        parent = hou.node("/mat") or hou.node("/").createNode("mat")

        def produce(builder):
            shader = builder.createNode("mtlxstandard_surface")
            texcoord = builder.createNode("mtlxtexcoord")
            uv = builder.createNode("mtlxconstant", "UVScale")
            uv.parm("value").set(cls.UV)
            scale = builder.createNode("mtlxmultiply")
            scale.parm("signature").set("vector2FA")
            scale.setNamedInput("in1", texcoord, 0)
            scale.setNamedInput("in2", uv, 0)
            albedo = builder.createNode("mtlximage")
            albedo.parm("signature").set("color3")
            albedo.parm("file").set(ALBEDO)
            albedo.setNamedInput("texcoord", scale, 0)
            tint = builder.createNode("mtlxconstant", "Tint")
            tint.parm("signature").set("color3")
            tint.parmTuple("value_color3").set(cls.TINT)
            tinted = builder.createNode("mtlxmultiply")
            tinted.parm("signature").set("color3")
            tinted.setNamedInput("in1", albedo, 0)
            tinted.setNamedInput("in2", tint, 0)
            shader.setNamedInput("base_color", tinted, 0)
            rough = builder.createNode("mtlxconstant", "Roughness")
            rough.parm("value").set(cls.ROUGH)
            dot = builder.createNode("mtlxdot")
            dot.setNamedInput("in", rough, 0)
            shader.setNamedInput("specular_roughness", dot, 0)
            return shader

        cls.source = nodes.build_karma_material(
            parent, "constants_source", produce).builder
        cls.builder, cls.shader, _wired, cls.report = \
            redshift_converter.convert_karma_builder(
                cls.source, parent, "constants_twin")

    @classmethod
    def tearDownClass(cls):
        for node in (cls.source, cls.builder):
            try:
                node.destroy()
            except hou.ObjectWasDeleted:
                pass

    def _child(self, type_name):
        found = [c for c in self.builder.children()
                 if c.type().name() == type_name]
        self.assertEqual(1, len(found), type_name)
        return found[0]

    def test_a_colour_constant_lands_on_the_multiply_it_fed(self):
        mul = self._child("redshift::RSMathMulVector")
        self.assertEqual(self.TINT, tuple(mul.parmTuple("input2").eval()))

    def test_a_uv_constant_lands_on_the_sampler_scale(self):
        sampler = self._child("redshift::TextureSampler")
        self.assertEqual((self.UV, self.UV),
                         tuple(sampler.parmTuple("scale").eval()))

    def test_a_constant_through_a_dot_lands_on_the_shader(self):
        self.assertAlmostEqual(
            self.ROUGH, self.shader.parm("refl_roughness").eval(), places=5)

    def test_nothing_is_reported_skipped(self):
        self.assertTrue(self.report.is_clean(),
                        "\n".join(self.report.summary_lines()))


@unittest.skipUnless(_redshift_available(),
                     "the Redshift plugin is not loaded")
class TheLibraryDoorMakesANewRedshiftEntry(unittest.TestCase):
    """`MaterialLibrary.convert_karma_to_redshift`: the saved Karma material is read back from disk, converted, and registered BESIDE the source, never in its place."""

    @classmethod
    def setUpClass(cls):
        if hou.getenv("OCIO") is None:
            hou.putenv("OCIO", "/dev/null")

    def setUp(self):
        from amaze.core import library as library_mod
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.render_on_import = 0
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        self.parent = hou.node("/mat") or hou.node("/").createNode("mat")
        self.source = _karma_material(self.parent, "karma_saved")
        self.addCleanup(self.source.destroy)
        self.assertEqual("Karma", self.model.add_asset(self.source, "Probe", "", False))
        self.row = len(self.model.assets) - 1

    def test_a_redshift_twin_is_added_beside_the_karma_source(self):
        before = len(self.model.assets)
        ok, report = self.model.convert_karma_to_redshift(self.model.index(self.row, 0))
        self.assertTrue(ok, report.summary_lines())
        self.assertEqual(before + 1, len(self.model.assets), "no new entry was added")
        source, twin = self.model.assets[self.row], self.model.assets[-1]
        self.assertEqual("Karma", source.renderer, "the source was changed")
        self.assertEqual("Redshift", twin.renderer)
        self.assertEqual(source.name, twin.name)
        self.assertEqual(list(source.categories), list(twin.categories))

    def test_the_twin_points_at_the_same_textures(self):
        ok, _report = self.model.convert_karma_to_redshift(self.model.index(self.row, 0))
        self.assertTrue(ok)
        twin = self.model.assets[-1]
        path = material.payload_path(self.prefs, twin.mat_id, self.prefs.ext)
        before = set(self.parent.children())
        self.parent.loadItemsFromFile(path)
        loaded = [n for n in self.parent.children() if n not in before]
        self.addCleanup(lambda: [n.destroy() for n in loaded])
        files = sorted(
            n.parm("tex0").unexpandedString()
            for top in loaded for n in [top] + list(top.allSubChildren())
            if n.type().name() == "redshift::TextureSampler")
        self.assertEqual(sorted([ALBEDO, NORMAL, ROUGH]), files,
                         "the saved Redshift network does not reference the source's own files")

    def test_the_twin_can_be_copied_into_a_lop_material_library(self):
        """A twin saved as an `rs_usd_material_builder` passes the import door's LOP check; a `redshift_vopnet` twin was refused with `Use Copy To /mat instead` (seen 2026-09-04)."""
        ok, _report = self.model.convert_karma_to_redshift(self.model.index(self.row, 0))
        self.assertTrue(ok)
        twin = self.model.assets[-1]
        handler = nodes.NodeHandler(self.prefs)
        self.assertEqual("rs_usd_material_builder",
                         handler.get_saved_node_type(twin))
        self.assertEqual({"mat", "lop"}, handler.import_targets(twin))

    def test_a_non_karma_row_is_refused_with_a_reason(self):
        self.model.assets[self.row].renderer = "Redshift"
        ok, report = self.model.convert_karma_to_redshift(self.model.index(self.row, 0))
        self.assertFalse(ok)
        self.assertTrue(report.skipped, "no reason given")


@unittest.skipUnless(_redshift_available(),
                     "the Redshift plugin is not loaded")
class ALegacyRedshiftMaterialGoesIntoSolaris(unittest.TestCase):
    """A material saved in the classic `redshift_vopnet` container used to be refused by Copy To /stage. Now the import door rebuilds it into the `rs_usd_material_builder` on the way in, the saved files untouched, so every Redshift material is LOP-capable."""

    def setUp(self):
        from amaze.core import library as library_mod
        cls = self
        cls.prefs = test_support.fixture_prefs(cls)
        cls.model = library_mod.MaterialLibrary(preferences=cls.prefs)
        cls.parent = hou.node("/mat") or hou.node("/").createNode("mat")
        legacy = cls.parent.createNode("redshift_vopnet")
        for child in list(legacy.children()):
            if child.type().name() != "redshift_material":
                child.destroy()
        classic = [c for c in legacy.children()
                   if c.type().name() == "redshift_material"][0]
        shader = legacy.createNode("redshift::StandardMaterial", "SM")
        shader.parmTuple("base_color").set((0.1, 0.9, 0.3))
        sampler = legacy.createNode("redshift::TextureSampler", "tex")
        shader.setNamedInput("refl_roughness", sampler, 0)
        bump = legacy.createNode("redshift::BumpMap", "bump")
        classic.setNamedInput("Surface", shader, 0)
        classic.setNamedInput("Bump Map", bump, 0)
        cls.model.add_asset(legacy, "Test", "", False, name="legacy_rs")
        cls.row = len(cls.model.assets) - 1
        legacy.destroy()

    def _imported(self):
        stage = hou.node("/stage")
        before = {n.path() for lib in stage.children()
                  if lib.type().name() == "materiallibrary"
                  for n in lib.children()}
        ok, reason, _created = self.model.import_asset_to_scene(
            self.model.index(self.row, 0), target="lop")
        self.assertTrue(ok, reason)
        after = [n for lib in stage.children()
                 if lib.type().name() == "materiallibrary"
                 for n in lib.children() if n.path() not in before]
        self.assertEqual(1, len(after), [n.path() for n in after])
        self.addCleanup(after[0].destroy)
        return after[0]

    def test_the_saved_files_still_say_the_classic_container(self):
        handler = nodes.NodeHandler(self.prefs)
        self.assertEqual("redshift_vopnet",
                         handler.get_saved_node_type(self.model.assets[self.row]))
        self.assertEqual({"mat", "lop"},
                         handler.import_targets(self.model.assets[self.row]))

    def test_it_lands_in_a_lop_library_as_the_usd_container(self):
        node = self._imported()
        self.assertEqual("rs_usd_material_builder", node.type().name())
        terminal = [c for c in node.children()
                    if c.type().name() == "redshift_usd_material"]
        self.assertEqual(1, len(terminal))
        feeds = {c.outputName(): c.inputNode().name()
                 for c in terminal[0].inputConnections()}
        self.assertEqual({"Surface": "SM", "BumpMap": "bump"}, feeds)
        shader = node.node("SM")
        self.assertEqual((0.1, 0.9, 0.3),
                         tuple(round(v, 3) for v in shader.parmTuple("base_color").eval()))
        self.assertEqual("tex", {c.outputName(): c.inputNode().name()
                                 for c in shader.inputConnections()}["refl_roughness"])
        self.assertFalse([c for c in node.children()
                          if c.type().name() == "redshift_material"],
                         "the classic terminal came along")


@unittest.skipUnless(_redshift_available(),
                     "the Redshift plugin is not loaded")
class AFirstEditionTwinGoesIntoSolaris(unittest.TestCase):
    """The twins 1.0.33 saved were a `redshift_vopnet` holding a USD terminal and no classic one. The upgrade used to look for the classic terminal alone, so such a twin arrived in the LOP library with its shader wired to a SECOND USD terminal and the one feeding the suboutput empty (seen 2026-09-04)."""

    def setUp(self):
        from amaze.core import library as library_mod
        self.prefs = test_support.fixture_prefs(self)
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        self.parent = hou.node("/mat") or hou.node("/").createNode("mat")
        legacy = self.parent.createNode("redshift_vopnet")
        for child in list(legacy.children()):
            child.destroy()
        usd = legacy.createNode("redshift_usd_material")
        shader = legacy.createNode("redshift::StandardMaterial",
                                   "mtlxstandard_surface1")
        disp = legacy.createNode("redshift::Displacement", "disp")
        usd.setNamedInput("Surface", shader, 0)
        usd.setNamedInput("Displacement", disp, 0)
        self.model.add_asset(legacy, "Test", "", False, name="first_twin")
        self.row = len(self.model.assets) - 1
        legacy.destroy()

    def test_one_usd_terminal_fed_and_feeding_the_suboutput(self):
        stage = hou.node("/stage")
        before = {n.path() for lib in stage.children()
                  if lib.type().name() == "materiallibrary"
                  for n in lib.children()}
        ok, reason, _created = self.model.import_asset_to_scene(
            self.model.index(self.row, 0), target="lop")
        self.assertTrue(ok, reason)
        node = [n for lib in stage.children()
                if lib.type().name() == "materiallibrary"
                for n in lib.children() if n.path() not in before][0]
        self.addCleanup(node.destroy)
        terminals = [c for c in node.children()
                     if c.type().name() in material.REDSHIFT_TERMINALS]
        self.assertEqual(["redshift_usd_material"],
                         [t.type().name() for t in terminals],
                         "the old terminal came along as a second one")
        feeds = {c.outputName(): c.inputNode().name()
                 for c in terminals[0].inputConnections()}
        self.assertEqual({"Surface": "mtlxstandard_surface1",
                          "Displacement": "disp"}, feeds)
        suboutput = [c for c in node.children()
                     if c.type().name() == "suboutput"]
        self.assertEqual(1, len(suboutput))
        self.assertEqual(
            [terminals[0].name()],
            [c.inputNode().name() for c in suboutput[0].inputConnections()],
            "the suboutput is not fed by the one terminal")


class _ValuesSource:
    """A values source with nothing to download: `fetch` answers the record's own payload, the way the measured-dataset sources do."""

    name = "PhysicallyBased"

    def fetch(self, record, resolution, dest_dir, progress=None):
        return {"values": record.payload.get("values", {})}


@unittest.skipUnless(_redshift_available(),
                     "the Redshift plugin is not loaded")
class AnOnlineMaterialCanLandAsRedshift(unittest.TestCase):
    """`matx_import.import_record(..., renderer="Redshift")`: the online record is built as the Karma network it always was, converted, and the Redshift twin is what the library registers."""

    @classmethod
    def setUpClass(cls):
        if hou.getenv("OCIO") is None:
            hou.putenv("OCIO", "/dev/null")

    def setUp(self):
        from amaze.core import library as library_mod
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.render_on_import = 0
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)

    def _record(self):
        from amaze.core import matx_sources
        return matx_sources.MatxRecord(
            source="PhysicallyBased", uid="probe-metal", title="Probe Metal",
            category="Metal", kind="values", licence="CC0 1.0",
            payload={"values": {"color": [0.8, 0.2, 0.1], "roughness": 0.3,
                                "metalness": 0.0}})

    def test_the_registered_entry_is_redshift(self):
        from amaze.core import matx_import
        before = len(self.model.assets)
        ok, reason = matx_import.import_record(
            self._record(), _ValuesSource(), "", self.model, self.prefs,
            renderer="Redshift")
        self.assertTrue(ok, reason)
        self.assertEqual(before + 1, len(self.model.assets))
        twin = self.model.assets[-1]
        self.assertEqual("Redshift", twin.renderer)
        path = material.payload_path(self.prefs, twin.mat_id, self.prefs.ext)
        parent = hou.node("/mat") or hou.node("/").createNode("mat")
        seen = set(parent.children())
        parent.loadItemsFromFile(path)
        loaded = [n for n in parent.children() if n not in seen]
        self.addCleanup(lambda: [n.destroy() for n in loaded])
        shaders = [n for top in loaded for n in [top] + list(top.allSubChildren())
                   if n.type().name() == "redshift::StandardMaterial"]
        self.assertEqual(1, len(shaders), "no Redshift shader in the saved network")
        self.assertEqual((0.8, 0.2, 0.1),
                         tuple(round(v, 3) for v in shaders[0].parmTuple("base_color").eval()))

    def test_a_measured_metal_lands_as_a_redshift_metal(self):
        """A complex-IOR measurement builds a MaterialX conductor with no standard surface; Redshift has no complex IOR, so the twin is a Standard Material at metalness 1 whose base colour is the measured normal-incidence reflectance. ▸r/redshift-nodes"""
        from amaze.core import matx_import, matx_sources
        gold = matx_sources.MatxRecord(
            source="PhysicallyBased", uid="probe-gold", title="Probe Gold",
            category="Metal", kind="values", licence="CC0 1.0",
            payload={"values": {"color": [1.0, 0.8, 0.4], "roughness": 0.2,
                                "complexIor": [0.18, 3.42, 0.42, 2.35, 1.37, 1.77]}})
        ok, reason = matx_import.import_record(
            gold, _ValuesSource(), "", self.model, self.prefs, renderer="Redshift")
        self.assertTrue(ok, reason)
        twin = self.model.assets[-1]
        self.assertEqual("Redshift", twin.renderer)
        path = material.payload_path(self.prefs, twin.mat_id, self.prefs.ext)
        parent = hou.node("/mat") or hou.node("/").createNode("mat")
        seen = set(parent.children())
        parent.loadItemsFromFile(path)
        loaded = [n for n in parent.children() if n not in seen]
        self.addCleanup(lambda: [n.destroy() for n in loaded])
        shader = next(n for top in loaded for n in [top] + list(top.allSubChildren())
                      if n.type().name() == "redshift::StandardMaterial")
        self.assertEqual(1.0, shader.parm("metalness").eval())
        self.assertAlmostEqual(0.2, shader.parm("refl_roughness").eval(), places=5)
        f0 = tuple(((n - 1) ** 2 + k ** 2) / ((n + 1) ** 2 + k ** 2)
                   for n, k in ((0.18, 3.42), (0.42, 2.35), (1.37, 1.77)))
        built = tuple(shader.parmTuple("base_color").eval())
        for want, got in zip(f0, built):
            self.assertAlmostEqual(want, got, places=4)

    def test_karma_is_still_the_default(self):
        from amaze.core import matx_import
        ok, reason = matx_import.import_record(
            self._record(), _ValuesSource(), "", self.model, self.prefs)
        self.assertTrue(ok, reason)
        self.assertEqual("Karma", self.model.assets[-1].renderer)

    def test_the_row_records_its_source_and_id(self):
        """Where a row came from and which record it is, on the row itself - until 2026-09-04 only the package folder name carried them, and only for downloads after 2026-08-05."""
        from amaze.core import matx_import
        record = self._record()
        ok, reason = matx_import.import_record(
            record, _ValuesSource(), "", self.model, self.prefs)
        self.assertTrue(ok, reason)
        row = self.model.assets[-1].get_as_dict()
        self.assertEqual(record.source, row.get("source"))
        self.assertEqual(str(record.uid), row.get("uid"))


if __name__ == "__main__":
    unittest.main()
