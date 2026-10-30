"""The Material Conversion Engine: every route through MaterialX, one API per renderer."""

import os
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

from amaze.core import library as library_mod  # noqa: E402
from amaze.actions import materials as material_actions  # noqa: E402
from amaze.core import material_files  # noqa: E402
from amaze.core import matx_import  # noqa: E402
from amaze.render import nodes  # noqa: E402
from amaze.render.material_conversion import engine, materialx  # noqa: E402
from amaze.render.material_conversion import octane as octane_api  # noqa: E402
from amaze.tests import test_support  # noqa: E402

plugins_loaded = test_support.plugins_loaded

BASE = (0.123, 0.456, 0.789)    # distinctive, so a default reappearing cannot pass as a copy
ALBEDO = "$AMAZELIB/matX/Test__pkg/textures/test_albedo.png"
GOLD = ((0.27, 0.68, 1.32), (3.6, 2.4, 1.8))    # a measured metal's (n, k) per channel
OCTANE = test_support.renderer_loaded("Octane")
REDSHIFT = test_support.renderer_loaded("Redshift")


def _textured(parent, name="karma_source"):
    """MaterialX with a colour map through a network dot, roughness through an mtlxdot, a Karma ramp."""
    builder = nodes.make_karma_builder(parent, name)
    shader = builder.createNode("mtlxstandard_surface")
    shader.parmTuple("base_color").set(BASE)
    image = builder.createNode("mtlximage")
    image.parm("signature").set("color3")
    image.parm("file").set(ALBEDO)
    dot = builder.createNetworkDot()
    dot.setInput(image, 0)
    shader.setInput(shader.inputIndex("base_color"), dot, 0)
    roughness = builder.createNode("mtlxconstant", "roughness")
    roughness.parm("value").set(0.7)
    passing = builder.createNode("mtlxdot")
    passing.setNamedInput("in", roughness, 0)
    shader.setNamedInput("specular_roughness", passing, 0)
    shader.setNamedInput("coat_color", builder.createNode("kma_rampconst", "karma_ramp"), 0)
    nodes.wire_builder_output(builder, shader)
    return builder


def _metal(parent, name="gold"):
    builder = nodes.make_karma_builder(parent, name)
    conductor = builder.createNode("mtlxconductor_bsdf")
    conductor.parmTuple("ior").set(GOLD[0])
    conductor.parmTuple("extinction").set(GOLD[1])
    conductor.parmTuple("roughness").set((0.2, 0.2))
    surface = builder.createNode("mtlxsurface")
    surface.setNamedInput("bsdf", conductor, 0)
    nodes.wire_builder_output(builder, surface)
    return builder


def _types(container):
    return sorted(child.type().name() for child in container.children())


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
        self.middle = container
        self.fed = materialx.terminal_feed(container).type().name()
        written = parent.createNode("subnet", "written")
        return engine.Converted(written, written, False, report)


class TheEngineRoutesThroughMaterialX(unittest.TestCase):
    """Routing and refusals with each plugin pinned, so the host decides nothing here."""

    def test_the_targets_are_the_menu_order(self):
        self.assertEqual(("Karma", "Redshift", "Octane"), engine.targets())

    def test_a_stored_materialx_name_reads_as_the_hub(self):
        for stored in ("Karma", "MaterialX", "MtlX"):
            self.assertIs(engine.api(engine.HUB), engine.api(stored), stored)

    def test_a_renderer_without_an_api_has_no_route(self):
        self.assertFalse(engine.has_route("Mantra", "Karma"))
        self.assertIn("no conversion", engine.why_not("Mantra", "Karma"))

    def test_the_same_renderer_is_refused(self):
        self.assertEqual("the material is already MaterialX", engine.why_not("Karma", "MaterialX"))

    def test_a_missing_plugin_refuses_at_either_end(self):
        with plugins_loaded("Octane"):
            self.assertIn("Redshift isn't loaded", engine.why_not("Karma", "Redshift"))
            self.assertIn("Redshift isn't loaded", engine.why_not("Redshift", "Octane"))
            self.assertTrue(engine.has_route("Redshift", "Octane"), "a route needs no plugin")

    def test_redshift_reaches_octane_when_both_load(self):
        with plugins_loaded("Redshift", "Octane"):
            self.assertTrue(engine.can_convert("Redshift", "Octane"))

    def test_every_renderer_reaches_every_other(self):
        with plugins_loaded("Redshift", "Octane"):
            for source in engine.targets():
                for target in engine.targets():
                    self.assertEqual(source != target, engine.can_convert(source, target),
                                     "%s to %s" % (source, target))

    def test_a_route_reads_into_the_hub_then_writes_from_it(self):
        reader, writer = _Reader(), _Writer()
        registry = {engine.HUB: engine.apis()[engine.HUB], "Reader": reader, "Writer": writer}
        scratch = hou.node("/obj").createNode("matnet")
        self.addCleanup(scratch.destroy)
        with mock.patch.dict(engine._registry, registry, clear=True):
            made = engine.convert(scratch, "Reader", "Writer", scratch, "My Mat")
        self.assertEqual("mtlxstandard_surface", writer.fed, "the writer read no MaterialX")
        with self.assertRaises(hou.ObjectWasDeleted):
            writer.middle.path()    # the MaterialX step is gone
        self.assertEqual("My_Mat", made.builder.name())
        self.assertEqual(1, made.report.skipped.count(engine.UNWIRED))


class RedshiftLoadsOnlyWithBothItsContainers(unittest.TestCase):
    """The converters build `rs_usd_material_builder` and read `redshift_vopnet`. ▸r/renderer-plugins"""

    BOTH = ("redshift_vopnet", "rs_usd_material_builder")

    def _why_not(self, present):
        """`why_not` in a host whose type registry holds `present` alone, in every category."""
        category = mock.Mock()
        category.nodeType.side_effect = lambda name: object() if name in present else None
        with mock.patch.object(hou, "nodeTypeCategories", lambda: {"Vop": category}), \
                mock.patch.object(hou, "nodeType", lambda cat, name: cat.nodeType(name)):
            return engine.why_not("Karma", "Redshift")

    def test_one_container_without_the_other_refuses_before_building(self):
        for present in (self.BOTH[:1], self.BOTH[1:], ()):
            with self.subTest(present=present):
                self.assertIn("Redshift isn't loaded", self._why_not(present))

    def test_both_containers_convert(self):
        self.assertEqual("", self._why_not(self.BOTH))


class TheLibraryDoorRefusesFirst(unittest.TestCase):
    """`actions.materials.convert` says why before it rebuilds anything."""

    @classmethod
    def setUpClass(cls):
        test_support.pin_env(test_support.class_scope(cls), "OCIO", "/dev/null")    # save_node gates on $OCIO; nothing renders here

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.render_on_import = 0
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        source = _textured(hou.node("/mat"))
        self.addCleanup(source.destroy)
        held = test_support.asset_ids(self.model)
        self.assertEqual("Karma", material_actions.add_asset(self.model, source, "Probe", "", False))
        self.source_id = str(test_support.arrived(self.model, held)[0].mat_id)

    @property
    def row(self):
        return self.model.find_asset_row_by_id(self.source_id)    # rows sort; the id holds

    def _convert(self, target):
        before = len(self.model.assets)
        with mock.patch.object(nodes.NodeHandler, "rebuild_saved",
                               side_effect=AssertionError("rebuilt before refusing")):
            ok, report = material_actions.convert(self.model, self.model.index(self.row, 0), target)
        self.assertFalse(ok)
        self.assertEqual(before, len(self.model.assets), "a refused conversion added a row")
        return report.skipped

    def test_a_material_already_the_target_is_refused(self):
        self.assertEqual(["the material is already MaterialX"], self._convert("Karma"))

    def test_a_missing_plugin_is_said(self):
        with plugins_loaded():
            self.assertEqual(["Octane isn't loaded in this Houdini, so the conversion can't run"],
                             self._convert("Octane"))


@unittest.skipUnless(OCTANE, "the Octane plugin is not loaded")
class AMaterialXMaterialBecomesOctanes(unittest.TestCase):
    """The network copied into Octane's builder, each node Octane refuses resolved or said."""

    @classmethod
    def setUpClass(cls):
        cls.parent = hou.node("/obj").createNode("matnet")
        cls.source = _textured(cls.parent)
        cls.before = _types(cls.source)
        cls.made = engine.convert(cls.source, "Karma", "Octane", cls.parent, "Brick Wall")

    @classmethod
    def tearDownClass(cls):
        cls.parent.destroy()

    def test_it_is_octanes_builder(self):
        builder = self.made.builder
        self.assertTrue(nodes.is_octane_builder(builder))
        self.assertEqual("Octane", nodes.NodeHandler(None).get_renderer_from_node(builder))
        self.assertTrue(self.made.wired)
        self.assertEqual("Brick_Wall", builder.name())

    def test_the_network_crosses_as_it_was(self):
        shader = self.made.shader
        for got, want in zip(shader.parmTuple("base_color").eval(), BASE):
            self.assertAlmostEqual(want, got, places=5)
        wire = next(c for c in shader.inputConnections()
                    if c.inputIndex() == shader.inputIndex("base_color"))
        self.assertIsInstance(wire.inputItem(), hou.NetworkDot, "the dot's routing was lost")
        self.assertEqual(ALBEDO, wire.inputNode().parm("file").unexpandedString())

    def test_a_pass_through_dot_is_wired_through(self):
        fed = self.made.shader.input(self.made.shader.inputIndex("specular_roughness"))
        self.assertEqual("roughness", fed.name() if fed else None)
        self.assertNotIn("mtlxdot", _types(self.made.builder))

    def test_a_karma_only_node_is_left_out_and_said(self):
        self.assertNotIn("kma_rampconst", _types(self.made.builder))
        self.assertTrue(any('"karma_ramp"' in line for line in self.made.report.skipped),
                        self.made.report.skipped)

    def test_nothing_octanes_filter_refuses_is_left(self):
        refused = [t for t in _types(self.made.builder) if not octane_api.admitted(t)]
        self.assertEqual([], refused)

    def test_the_source_is_untouched(self):
        self.assertEqual(self.before, _types(self.source))


@unittest.skipUnless(OCTANE, "the Octane plugin is not loaded")
class AMeasuredMetalBecomesAMetalnessSurface(unittest.TestCase):

    def test_its_colour_is_the_head_on_reflectance(self):
        parent = hou.node("/obj").createNode("matnet")
        self.addCleanup(parent.destroy)
        made = engine.convert(_metal(parent), "Karma", "Octane", parent, "Gold")
        self.assertEqual("mtlxstandard_surface", made.shader.type().name())
        self.assertTrue(made.wired)
        self.assertEqual(1.0, made.shader.parm("metalness").eval())
        for got, n, k in zip(made.shader.parmTuple("base_color").eval(), *GOLD):
            self.assertAlmostEqual(materialx.normal_incidence_reflectance(n, k), got, places=5)
        self.assertAlmostEqual(0.2, made.shader.parm("specular_roughness").eval(), places=5)
        self.assertEqual(1, len(made.report.approximated), made.report.approximated)
        self.assertNotIn("mtlxconductor_bsdf", _types(made.builder))


@unittest.skipUnless(OCTANE, "the Octane plugin is not loaded")
class WhatOctaneIgnoresIsSaidOnlyWhenUsed(unittest.TestCase):

    def _report(self, dress):
        parent = hou.node("/obj").createNode("matnet")
        self.addCleanup(parent.destroy)
        builder = nodes.make_karma_builder(parent, "probe")
        shader = builder.createNode("mtlxstandard_surface")
        image = builder.createNode("mtlximage")
        shader.setNamedInput("base_color", image, 0)
        nodes.wire_builder_output(builder, shader)
        dress(shader, image)
        return engine.convert(builder, "Karma", "Octane", parent, "probe").report.skipped

    def test_inputs_at_their_defaults_say_nothing(self):
        self.assertEqual([], self._report(lambda shader, image: None))

    def test_a_mix_of_two_surfaces_is_said(self):
        parent = hou.node("/obj").createNode("matnet")
        self.addCleanup(parent.destroy)
        builder = nodes.make_karma_builder(parent, "mixed")
        mix = builder.createNode("mtlxmix")
        mix.setNamedInput("fg", builder.createNode("mtlxstandard_surface"), 0)
        mix.setNamedInput("bg", builder.createNode("mtlxstandard_surface"), 0)
        nodes.wire_builder_output(builder, mix)
        skipped = engine.convert(builder, "Karma", "Octane", parent, "mixed").report.skipped
        self.assertTrue(any("mixes two surfaces" in line for line in skipped), skipped)

    def test_a_used_input_is_named(self):
        def dress(shader, image):
            image.parm("filtertype").set("closest")
            shader.parm("coat_affect_color").set(0.5)
        skipped = self._report(dress)
        self.assertEqual(2, len(skipped), skipped)
        self.assertTrue(any("filtertype" in line for line in skipped), skipped)
        self.assertTrue(any("coat_affect_color" in line for line in skipped), skipped)


@unittest.skipUnless(OCTANE, "the Octane plugin is not loaded")
class TheOctaneTwinLivesInTheLibrary(unittest.TestCase):
    """Convert to Octane saves Octane's builder beside the source, and it goes back into a scene."""

    @classmethod
    def setUpClass(cls):
        test_support.pin_env(test_support.class_scope(cls), "OCIO", "/dev/null")

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.render_on_import = 0
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        self.mat = hou.node("/mat")
        self.before = {n.path() for n in self.mat.children()}
        self.addCleanup(self._clear_mat)
        source = _textured(self.mat, "brick_source")
        held = test_support.asset_ids(self.model)
        self.assertEqual("Karma", material_actions.add_asset(self.model, source, "Probe", "", False,
                                                       name="Brick Wall"))
        self.source_id = str(test_support.arrived(self.model, held)[0].mat_id)
        held = test_support.asset_ids(self.model)
        ok, report = material_actions.convert(self.model, self.model.index(self.row, 0), "Octane")
        self.assertTrue(ok, report.summary_lines())
        self.twin, = test_support.arrived(self.model, held)

    @property
    def row(self):
        return self.model.find_asset_row_by_id(self.source_id)    # the twin sorted in beside it

    def _clear_mat(self):
        for child in self.mat.children():
            if child.path() not in self.before:
                try:
                    child.destroy()
                except hou.Error:
                    pass

    def _imported(self, target="mat", context=None):
        ok, reason, created = nodes.NodeHandler(self.prefs).import_asset_to_scene(
            self.twin, target=target, context_node=context)
        self.assertTrue(ok, reason)
        return created[0]

    def test_the_twin_sits_beside_the_source(self):
        source = self.model.assets[self.row]
        self.assertEqual("Karma", source.renderer, "the source was changed")
        self.assertEqual("Octane", self.twin.renderer)
        self.assertEqual(source.name, self.twin.name)
        self.assertEqual(list(source.categories), list(self.twin.categories))
        self.assertEqual("subnet", material_files.get_saved_node_type(self.prefs, self.twin))

    def test_it_comes_back_as_octanes_builder(self):
        imported = self._imported()
        self.assertTrue(nodes.is_octane_builder(imported))
        self.assertTrue(nodes.surface_terminal_wired(imported))
        shader = materialx.terminal_feed(imported)
        for got, want in zip(shader.parmTuple("base_color").eval(), BASE):
            self.assertAlmostEqual(want, got, places=5)

    def test_it_goes_into_a_material_library(self):
        self.assertEqual({"mat", "lop"},
                         nodes.NodeHandler(self.prefs).import_targets(self.twin))
        stage = hou.node("/obj").createNode("lopnet", "octane_twin_probe")
        self.addCleanup(stage.destroy)
        library = self._imported(target="lop", context=stage).parent()
        from pxr import UsdShade
        outputs = [o.GetFullName()
                   for prim in library.stage().Traverse()
                   if prim.GetTypeName() == "Material"
                   for o in UsdShade.Material(prim).GetOutputs()]
        self.assertIn("outputs:mtlx:surface", outputs)


@unittest.skipUnless(OCTANE, "the Octane plugin is not loaded")
class AnOnlineImportCanLandAsOctane(unittest.TestCase):

    def test_the_materialx_build_is_replaced_by_its_octane_twin(self):
        scratch = hou.node("/obj").createNode("matnet")
        self.addCleanup(scratch.destroy)
        built = _textured(scratch, "Online_Brick")
        builder, shader, wired, report = matx_import.to_renderer(
            built, scratch, "Online Brick", "Octane")
        self.assertTrue(nodes.is_octane_builder(builder))
        self.assertTrue(wired)
        self.assertEqual("Online_Brick", builder.name(), "the twin kept a `1`")
        self.assertEqual([builder], list(scratch.children()), "the MaterialX build was left")


@unittest.skipUnless(OCTANE and REDSHIFT, "Redshift and Octane are not both loaded")
class ARedshiftMaterialReachesOctane(unittest.TestCase):
    """Redshift to MaterialX to Octane: one report, the MaterialX step gone."""

    def test_the_base_colour_crosses_both_steps(self):
        parent = hou.node("/obj").createNode("matnet")
        self.addCleanup(parent.destroy)
        source = parent.createNode("redshift_vopnet")
        for child in list(source.children()):
            if child.type().name() != "redshift_material":
                child.destroy()
        shader = source.createNode("redshift::StandardMaterial")
        shader.parmTuple("base_color").set(BASE)
        next(c for c in source.children() if c.type().name() == "redshift_material"
             ).setNamedInput("Surface", shader, 0)
        made = engine.convert(source, "Redshift", "Octane", parent, "Red Probe")
        self.assertTrue(nodes.is_octane_builder(made.builder), made.report.summary_lines())
        for got, want in zip(made.shader.parmTuple("base_color").eval(), BASE):
            self.assertAlmostEqual(want, got, places=5)
        self.assertEqual("Red_Probe", made.builder.name())
        self.assertEqual(2, len(parent.children()), "the MaterialX step was left behind")


def _octane_net(parent, shader_type="octane::NT_MAT_STANDARD_SURFACE", name="octane_source"):
    """A classic Octane container holding one `shader_type` wired to its output."""
    net = parent.createNode("octane_vopnet", name)
    for child in list(net.children()):
        if child.type().name().startswith("octane::"):
            child.destroy()
    shader = net.createNode(shader_type)
    net.node("suboutput1").setInput(0, shader, 0)
    return net, shader


def _feeding(node, name):
    """What feeds `node`'s input `name`, or None."""
    index = node.inputIndex(name)
    return node.input(index) if index >= 0 else None


@unittest.skipUnless(OCTANE, "the Octane plugin is not loaded")
class TheOctaneReaderTablesNameRealInputs(unittest.TestCase):
    """Every name in the reader's tables exists on its node: a typo would copy nothing, silently."""

    def test_both_columns_of_both_shader_tables(self):
        from amaze.render.material_conversion import octane_reader
        parent = hou.node("/obj").createNode("matnet")
        self.addCleanup(parent.destroy)
        net = parent.createNode("octane_vopnet")
        builder = nodes.make_karma_builder(parent, "names")
        for octane_type, mtlx_type, pairs in (
                ("octane::NT_MAT_STANDARD_SURFACE", "mtlxstandard_surface",
                 octane_reader.STANDARD_SURFACE),
                ("octane::NT_MAT_OPEN_PBR_SURFACE", "mtlxopen_pbr_surface",
                 octane_reader.OPEN_PBR)):
            source, target = net.createNode(octane_type), builder.createNode(mtlx_type)
            missing = [o for o, _m in pairs if o not in source.inputNames()]
            missing += [m for _o, m in pairs if target.parmTuple(m) is None]
            self.assertEqual([], missing, octane_type)


@unittest.skipUnless(OCTANE, "the Octane plugin is not loaded")
class AnOctaneMaterialBecomesMaterialX(unittest.TestCase):
    """Octane's own nodes read into MaterialX, by the semantics measured in Octane."""

    def setUp(self):
        self.parent = hou.node("/obj").createNode("matnet")
        self.addCleanup(self.parent.destroy)

    def _convert(self, net):
        made = engine.convert(net, "Octane", "Karma", self.parent, "From Octane")
        self.assertIsNotNone(made.builder, made.report.summary_lines())
        return made

    def test_a_standard_surface_crosses_by_name(self):
        net, shader = _octane_net(self.parent)
        shader.parmTuple("baseColor").set(BASE)
        shader.parm("roughness").set(0.37)
        shader.parm("metallic").set(0.6)
        made = self._convert(net)
        self.assertEqual("mtlxstandard_surface", made.shader.type().name())
        self.assertTrue(made.wired)
        for got, want in zip(made.shader.parmTuple("base_color").eval(), BASE):
            self.assertAlmostEqual(want, got, places=5)
        self.assertAlmostEqual(0.37, made.shader.parm("specular_roughness").eval(), places=5)
        self.assertAlmostEqual(0.6, made.shader.parm("metalness").eval(), places=5)
        self.assertTrue(made.report.is_clean(), made.report.summary_lines())

    def test_an_image_keeps_its_file_and_colour_space(self):
        net, shader = _octane_net(self.parent)
        image = net.createNode("octane::NT_TEX_IMAGE")
        image.parm("A_FILENAME").set(ALBEDO)
        image.parm("colorSpace").set("NAMED_COLOR_SPACE_LINEAR_SRGB")
        shader.setNamedInput("baseColor", image, 0)
        fed = _feeding(self._convert(net).shader, "base_color")
        self.assertEqual("mtlximage", fed.type().name())
        self.assertEqual(ALBEDO, fed.parm("file").unexpandedString())
        self.assertEqual("lin_rec709", fed.parm("filecolorspace").evalAsString())

    def test_a_normal_image_becomes_a_normal_map_read_raw(self):
        net, shader = _octane_net(self.parent)
        image = net.createNode("octane::NT_TEX_IMAGE")
        image.parm("A_FILENAME").set(ALBEDO)
        shader.setNamedInput("normal", image, 0)
        normalmap = _feeding(self._convert(net).shader, "normal")
        self.assertTrue(normalmap.type().name().startswith("mtlxnormalmap"))
        read = _feeding(normalmap, "in")
        self.assertEqual("vector3", read.parm("signature").evalAsString())
        self.assertEqual("Raw", read.parm("filecolorspace").evalAsString())

    def test_a_2d_transform_turns_and_scales_about_the_centre(self):
        net, shader = _octane_net(self.parent)
        image = net.createNode("octane::NT_TEX_IMAGE")
        transform = net.createNode("octane::NT_TRANSFORM_2D")
        transform.parm("rotation").set(30.0)
        transform.parmTuple("translation").set((0.1, 0.05))
        image.setNamedInput("transform", transform, 0)
        shader.setNamedInput("baseColor", image, 0)
        place = _feeding(_feeding(self._convert(net).shader, "base_color"), "texcoord")
        self.assertEqual("mtlxplace2d", place.type().name())
        self.assertEqual((0.5, 0.5), tuple(place.parmTuple("pivot").eval()))
        self.assertEqual("1", place.parm("operationorder").evalAsString())
        self.assertAlmostEqual(30.0, place.parm("rotate").eval(), places=4)

    def _colour(self, net, value):
        node = net.createNode("octane::NT_TEX_RGB")
        node.parmTuple("A_VALUE").set(value)
        return node

    def _constant(self, node):
        return tuple(round(v, 4) for v in node.parmTuple("value_color3").eval())

    def test_a_mix_texture_shows_texture1_at_zero(self):
        net, shader = _octane_net(self.parent)
        mix = net.createNode("octane::NT_TEX_MIX")
        mix.setNamedInput("texture1", self._colour(net, (0.9, 0.1, 0.1)), 0)
        shader.setNamedInput("baseColor", mix, 0)
        converted = _feeding(self._convert(net).shader, "base_color")
        self.assertEqual((0.9, 0.1, 0.1), self._constant(_feeding(converted, "bg")))

    def test_a_mix_material_shows_material1_at_one(self):
        net, mix = _octane_net(self.parent, "octane::NT_MAT_MIX")
        mix.parm("amount").set(0.3)
        for slot, colour in (("material1", BASE), ("material2", (0.5, 0.5, 0.5))):
            part = net.createNode("octane::NT_MAT_STANDARD_SURFACE")
            part.parmTuple("baseColor").set(colour)
            mix.setNamedInput(slot, part, 0)
        made = self._convert(net)
        self.assertEqual("mtlxmix", made.shader.type().name())
        foreground = _feeding(made.shader, "fg").parmTuple("base_color").eval()
        for got, want in zip(foreground, BASE):
            self.assertAlmostEqual(want, got, places=5)
        self.assertAlmostEqual(0.3, made.shader.parm("mix").eval(), places=5)

    def test_subtract_takes_texture1_first(self):
        net, shader = _octane_net(self.parent)
        subtract = net.createNode("octane::NT_TEX_SUBTRACT")
        subtract.setNamedInput("texture1", self._colour(net, (0.9, 0.9, 0.9)), 0)
        subtract.setNamedInput("texture2", self._colour(net, (0.2, 0.2, 0.2)), 0)
        shader.setNamedInput("baseColor", subtract, 0)
        converted = _feeding(self._convert(net).shader, "base_color")
        self.assertEqual(((0.9, 0.9, 0.9), (0.2, 0.2, 0.2)),
                         (self._constant(_feeding(converted, "in1")),
                          self._constant(_feeding(converted, "in2"))))

    def test_displacement_is_height_from_its_mid_level(self):
        net, shader = _octane_net(self.parent)
        displacement = net.createNode("octane::NT_DISPLACEMENT")
        displacement.parm("amount").set(0.2)
        displacement.parm("black_level").set(0.5)
        displacement.setNamedInput("texture", net.createNode("octane::NT_TEX_FLOATIMAGE"), 0)
        shader.setNamedInput("displacement", displacement, 0)
        made = self._convert(net)
        terminal = materialx.terminal_feed(made.builder, "displacement")
        self.assertEqual("mtlxdisplacement", terminal.type().name())
        self.assertAlmostEqual(0.2, terminal.parm("scale").eval(), places=5)
        self.assertEqual("mtlxsubtract", _feeding(terminal, "displacement").type().name())

    def test_a_refused_material_says_why(self):
        net, _toon = _octane_net(self.parent, "octane::NT_MAT_TOON")
        made = engine.convert(net, "Octane", "Karma", self.parent, "Toon")
        self.assertIsNone(made.shader)
        self.assertTrue(any("Toon" in line for line in made.report.skipped),
                        made.report.skipped)

    def test_an_unmapped_texture_is_said_and_the_value_kept(self):
        net, shader = _octane_net(self.parent)
        shader.parmTuple("baseColor").set(BASE)
        shader.setNamedInput("baseColor", net.createNode("octane::NT_TEX_TRIPLANAR"), 0)
        made = self._convert(net)
        self.assertIsNone(_feeding(made.shader, "base_color"))
        for got, want in zip(made.shader.parmTuple("base_color").eval(), BASE):
            self.assertAlmostEqual(want, got, places=5)
        self.assertTrue(any("triplanar" in line for line in made.report.skipped),
                        made.report.skipped)

    def test_materialx_inside_octanes_builder_crosses_as_it_is(self):
        builder = nodes.make_karma_builder(self.parent, "mixed")
        surface = builder.createNode("mtlxstandard_surface", "kept")
        surface.parmTuple("base_color").set(BASE)
        nodes.wire_builder_output(builder, surface)
        octane_api.mark(builder)
        made = self._convert(builder)
        self.assertEqual("mtlxstandard_surface", made.shader.type().name())
        for got, want in zip(made.shader.parmTuple("base_color").eval(), BASE):
            self.assertAlmostEqual(want, got, places=5)


@unittest.skipUnless(OCTANE, "the Octane plugin is not loaded")
class AnOctaneTwinIsMaterialXInTheLibrary(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        test_support.pin_env(test_support.class_scope(cls), "OCIO", "/dev/null")

    def test_convert_saves_a_materialx_twin_beside_it(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        prefs = test_support.fixture_prefs(self)
        prefs.render_on_import = 0
        model = library_mod.MaterialLibrary(preferences=prefs)
        mat = hou.node("/mat")
        net, shader = _octane_net(mat, name="octane_twin_source")
        self.addCleanup(net.destroy)
        shader.parmTuple("baseColor").set(BASE)
        held = test_support.asset_ids(model)
        self.assertEqual("Octane", material_actions.add_asset(model, net, "Probe", "", False, name="Octane Red"))
        source, = test_support.arrived(model, held)
        held = test_support.asset_ids(model)
        ok, report = material_actions.convert(model,
            model.index(model.find_asset_row_by_id(source.mat_id), 0), "Karma")
        self.assertTrue(ok, report.summary_lines())
        twin, = test_support.arrived(model, held)
        self.assertEqual(("Karma", "Octane Red"), (twin.renderer, twin.name))


if __name__ == "__main__":
    unittest.main()
