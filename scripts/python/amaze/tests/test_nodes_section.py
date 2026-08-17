"""Node networks saved and reloaded from ANY context, on real networks and a fixture library. AmazeNotes practice.md ▸p/nodes-section"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(        # THREE dirnames: tests/ -> amaze/ -> python/. Four lands on scripts/, where the tests import the INSTALL - test_roundtrip.py
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import cop_library  # noqa: E402
from amaze.render import thumbs  # noqa: E402
from amaze.tests import test_support  # noqa: E402


def _sop_network(name: str) -> hou.Node:
    """A geo with two CONNECTED nodes - the connection is half of what the round-trip must preserve."""
    geo = hou.node("/obj").createNode("geo", name)
    box = geo.createNode("box", "the_box")
    mountain = geo.createNode("mountain", "the_mountain")
    mountain.setFirstInput(box)
    mountain.setDisplayFlag(True)
    return geo


def _cop_node_type() -> str:
    """Whatever this build calls a simple COP - type names moved with Copernicus, so ask rather than assume."""
    kinds = hou.copNodeTypeCategory().nodeTypes()
    for wanted in ("ramp", "gradient", "color", "constant", "noise"):
        if wanted in kinds:
            return wanted
    return sorted(kinds)[0]


class NodesSectionTest(unittest.TestCase):

    def setUp(self):
        test_support.reset_database_singletons()    # connectors cache per FILENAME, so without this every test after the first reads the previous test's cops.json
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.render_on_import = 0
        self.model = cop_library.CopLibrary(preferences=self.prefs)
        self.addCleanup(self._clear_obj)

    def _clear_obj(self):
        for child in hou.node("/obj").children():
            try:
                child.destroy()
            except hou.OperationFailed:
                pass

    def _image_for(self, asset) -> str:
        return os.path.join(self.prefs.dir, self.prefs.img_dir,
                            str(asset.mat_id) + self.prefs.img_ext)


    def test_context_of_reads_the_containing_network(self):
        geo = _sop_network("ctx_sop")
        cop = hou.node("/obj").createNode("copnet", "ctx_cop")
        lop = hou.node("/obj").createNode("lopnet", "ctx_lop")
        self.assertEqual("Sop", self.model.context_of(geo))
        self.assertEqual("Cop", self.model.context_of(cop))
        self.assertEqual("Lop", self.model.context_of(lop))

    def test_context_of_selection_matches_its_network(self):
        """A selection is described by where it LIVES - node.parent() when items are given, or a SOP selection reports /obj."""
        geo = _sop_network("ctx_sel")
        items = [geo.node("the_box")]
        self.assertEqual("Sop", self.model.context_of(items[0], items))
        self.assertEqual(self.model.context_of(geo),
                         self.model.context_of(items[0], items))

    def test_label_is_recorded_on_the_asset(self):
        geo = _sop_network("label_src")
        label = self.model.add_asset(geo, "", "", False, name="labelled")
        self.assertEqual("SOP", label)
        self.assertEqual("SOP", self.model.assets[-1].renderer)


    def test_the_import_seam_returns_what_it_created(self):
        """(ok, reason, created): the seam every drop-position behaviour rides, so no caller diffs children."""
        from amaze.helpers import helpers

        geo = _sop_network("seam_src")
        self.assertEqual("SOP", self.model.add_asset(
            geo, "", "", False, name="seam_sop"))
        geo.destroy()

        dest = hou.node("/obj").createNode("geo", "seam_dest")
        ok, reason, created = self.model.import_asset_to_scene(
            self.model.index(0, 0), context_node=dest)
        self.assertTrue(ok, reason)
        self.assertTrue(created,
                        "a successful import returned no created nodes")
        spot = hou.Vector2(6.0, -4.0)
        helpers.place_nodes(created, spot)
        anchor = helpers.centred_on(spot)       # a half-size short: the BODY centres on the drop point, the host's own new-node convention
        xs = [n.position().x() for n in created]
        ys = [n.position().y() for n in created]
        self.assertAlmostEqual(anchor.x(), sum(xs) / len(xs),
                               msg="the group centroid missed the spot")
        self.assertAlmostEqual(anchor.y(), sum(ys) / len(ys))

    def test_an_unsafe_id_is_refused_with_a_sentence(self):
        """An id that cannot be a filename gets a sentence, not a traceback - practice.md ▸p/nodes-section."""
        geo = _sop_network("unsafe_src")
        self.assertEqual("SOP", self.model.add_asset(
            geo, "", "", False, name="unsafe_sop"))
        geo.destroy()
        self.model.assets[0]._mat_id = "../../../Documents/x"   # the private field: mat_id is read-only by design, and a hand-edited cops.json is the only way such an id reaches a row

        ok, reason, _created = self.model.import_asset_to_scene(
            self.model.index(0, 0))
        self.assertFalse(ok, "an id that cannot be a filename imported")
        self.assertIn("cannot be imported", reason,
                      "the refusal did not say what was wrong: %r" % reason)

    def test_sop_network_returns_intact(self):
        geo = _sop_network("rt_src")
        self.assertEqual("SOP", self.model.add_asset(
            geo, "", "", False, name="rt_sop"))
        geo.destroy()

        dest = hou.node("/obj").createNode("geo", "rt_dest")
        ok, reason, _created = self.model.import_asset_to_scene(
            self.model.index(0, 0), context_node=dest)
        self.assertTrue(ok, reason)

        names = {n.name(): n for n in dest.children()}
        self.assertIn("the_box", names)
        self.assertIn("the_mountain", names)
        self.assertEqual(
            "the_box", names["the_mountain"].inputs()[0].name(),
            "the connection between the saved nodes did not survive")

    def test_selection_of_one_node_returns(self):
        geo = _sop_network("sel_src")
        box = geo.node("the_box")
        # A selection is passed as one of the SELECTED items, not the container - the network is reached through its parent.
        self.assertEqual("SOP", self.model.add_asset(
            box, "", "", False, items=[box], name="sel_one"))
        geo.destroy()

        dest = hou.node("/obj").createNode("geo", "sel_dest")
        ok, reason, _created = self.model.import_asset_to_scene(
            self.model.index(0, 0), context_node=dest)
        self.assertTrue(ok, reason)
        self.assertEqual(["the_box"], [n.name() for n in dest.children()])


    def test_a_foreign_context_gets_a_container_where_one_exists(self):
        """A Copernicus network CAN hold SOPs, in a sopnet - so this builds one rather than refusing."""
        geo = _sop_network("foreign_src")
        self.model.add_asset(geo, "", "", False, name="SOPwhole")
        geo.destroy()

        dest = hou.node("/obj").createNode("copnet", "foreign_dest")
        ok, reason, made = self._import_into("SOPwhole", dest)
        self.assertTrue(ok, reason)
        self.assertEqual(1, len(made))
        self.assertEqual("sopnet", made[0].type().name())
        self.assertIn("the_box", {n.name() for n in made[0].children()})

    def test_it_still_refuses_where_nothing_can_hold_them(self):
        """The refusal must survive the widening: a matnet has no home for SOPs at any depth."""
        geo = _sop_network("refuse_src")
        self.model.add_asset(geo, "", "", False, name="SOPwhole")
        geo.destroy()

        dest = hou.node("/obj").createNode("matnet", "refuse_dest")
        before = len(dest.children())
        ok, reason, made = self._import_into("SOPwhole", dest)

        self.assertFalse(ok)
        self.assertIn("SOP", reason)
        self.assertEqual([], made)
        self.assertEqual(before, len(dest.children()),
                         "a refused import left nodes behind")


    def _import_into(self, name, dest):
        """Save-free helper: import asset `name` into dest -> (ok, reason, the nodes it created there)."""
        row = [i for i, a in enumerate(self.model.assets) if a.name == name][0]
        before = set(dest.children())
        ok, reason, _created = self.model.import_asset_to_scene(
            self.model.index(row, 0), context_node=dest)
        return ok, reason, [c for c in dest.children() if c not in before]

    def test_a_network_asset_lands_at_object_level_in_its_container(self):
        """Every context with a home in /obj must get one - building the container IS the answer there, not the failure case."""
        sources = {
            "SOPnet": _sop_network("obj_sop"),
            "COPnet": hou.node("/obj").createNode("copnet", "obj_cop"),
            "LOPnet": hou.node("/obj").createNode("lopnet", "obj_lop"),
        }
        sources["COPnet"].createNode(_cop_node_type())
        sources["LOPnet"].createNode("sphere")
        for name, node in sources.items():
            self.model.add_asset(node, "", "", False, name=name)
            node.destroy()

        expected = {"SOPnet": "geo", "COPnet": "copnet", "LOPnet": "lopnet"}
        for name, container_type in expected.items():
            ok, reason, made = self._import_into(name, hou.node("/obj"))
            self.assertTrue(ok, "%s: %s" % (name, reason))
            self.assertEqual(1, len(made), "%s made %s" % (name, made))
            self.assertEqual(container_type, made[0].type().name())
            self.assertTrue(made[0].children(),
                            "%s came back as an empty container" % name)

    def test_an_object_selection_loads_straight_into_obj(self):
        """Object-context nodes ARE /obj's own kind - no container."""
        first = hou.node("/obj").createNode("geo", "objA")
        second = hou.node("/obj").createNode("geo", "objB")
        self.model.add_asset(first, "", "", False,
                             items=[first, second], name="OBJsel")
        first.destroy()
        second.destroy()

        ok, reason, made = self._import_into("OBJsel", hou.node("/obj"))
        self.assertTrue(ok, reason)
        self.assertEqual({"objA", "objB"}, {n.name() for n in made})

    def test_object_nodes_are_refused_inside_a_sop_network(self):
        """The trap: every context has a `subnet`, so a SOP subnet looks like a home for object-level nodes and is not one."""
        first = hou.node("/obj").createNode("geo", "trapA")
        second = hou.node("/obj").createNode("geo", "trapB")
        self.model.add_asset(first, "", "", False,
                             items=[first, second], name="OBJtrap")
        first.destroy()
        second.destroy()

        dest = hou.node("/obj").createNode("geo", "trap_dest")
        ok, reason, made = self._import_into("OBJtrap", dest)
        self.assertFalse(ok, "object nodes were built inside a SOP network")
        self.assertEqual([], made)
        self.assertIn("OBJECT", reason)


    def test_every_destination_and_context_pairing(self):
        """The whole matrix - asking the registry for ANY type that fits answered /stage+SOP with `copytopoints`."""
        obj = hou.node("/obj")
        dests = {
            "/obj": obj,
            "/stage": hou.node("/stage"),
            "geo": obj.createNode("geo", "m_geo"),
            "copnet": obj.createNode("copnet", "m_cop"),
            "lopnet": obj.createNode("lopnet", "m_lop"),
            "matnet": obj.createNode("matnet", "m_mat"),
        }
        saved = {"Sop": "geo", "Cop": "copnet", "Lop": "lopnet",
                 "Object": "subnet"}
        expected = {
            ("/obj", "Sop"): "geo",
            ("/obj", "Cop"): "copnet",
            ("/obj", "Lop"): "lopnet",
            ("/obj", "Object"): "subnet",
            ("/stage", "Sop"): "sopcreate",     # Solaris hosts SOPs in a SOP Create, the node that turns geometry into USD; a bare sopnet there is invisible to the stage
            ("/stage", "Cop"): "copnet",
            ("/stage", "Lop"): "lopnet",
            ("/stage", "Object"): None,
            ("geo", "Cop"): "copnet",
            ("geo", "Lop"): "lopnet",           # LOP nodes dropped in a SOP network get a LOP network
            ("geo", "Object"): None,
            ("copnet", "Sop"): "sopnet",
            ("lopnet", "Sop"): "sopcreate",
            ("matnet", "Sop"): None,            # materials are the material section's business
            ("matnet", "Cop"): None,
            ("matnet", "Object"): None,
        }
        for (dest_name, context), want in expected.items():
            got = self.model.container_type_in(
                dests[dest_name], context, saved.get(context, ""))
            self.assertEqual(
                want, got,
                "%s + %s asset -> %r, expected %r"
                % (dest_name, context, got, want))

    def test_a_sop_network_lands_in_a_sop_create_in_solaris(self):
        geo = _sop_network("solaris_src")
        self.model.add_asset(geo, "", "", False, name="ForStage")
        geo.destroy()

        stage = hou.node("/stage")
        ok, reason, made = self._import_into("ForStage", stage)
        self.assertTrue(ok, reason)
        self.assertEqual(1, len(made))
        self.assertEqual("sopcreate", made[0].type().name())

        target = self.model.load_target_in(made[0], "Sop")      # DiveTarget and EditableNodes both read sopnet/create, two levels down - practice.md ▸p/nodes-section
        self.assertEqual("sopnet/create", target.path().split(
            made[0].path() + "/")[-1])
        landed = {n.name() for n in target.children()}
        self.assertIn("the_box", landed)
        self.assertIn("the_mountain", landed)
        self.assertEqual(
            "the_box",
            target.node("the_mountain").inputs()[0].name(),
            "the connection did not survive the trip into Solaris")

        self.assertTrue(made[0].matchesCurrentDefinition(),
                        "the SOP Create was unlocked - diving will show "
                        "its internals instead of the imported nodes")

        flagged = [n.name() for n in target.children()
                   if n.isDisplayFlagSet()]
        self.assertEqual(["the_mountain"], flagged)
        meshes = [p.GetPath().pathString for p in made[0].stage().Traverse()
                  if p.GetTypeName() == "Mesh"]
        self.assertTrue(meshes, "the stage carries no geometry")

    def test_an_unflagged_network_still_reaches_the_stage(self):
        """The flag fallback is invisible until a save whose nodes had none, and then the stage is empty."""
        geo = hou.node("/obj").createNode("geo", "unflagged_src")
        box = geo.createNode("box", "the_box")
        mountain = geo.createNode("mountain", "the_mountain")
        mountain.setFirstInput(box)
        for node in (box, mountain):
            node.setDisplayFlag(False)
            node.setRenderFlag(False)
        self.model.add_asset(geo, "", "", False, name="Unflagged")
        geo.destroy()

        ok, reason, made = self._import_into("Unflagged", hou.node("/stage"))
        self.assertTrue(ok, reason)
        target = self.model.load_target_in(made[0], "Sop")
        flagged = [n.name() for n in target.children()
                   if n.isDisplayFlagSet()]
        self.assertEqual(
            ["the_mountain"], flagged,
            "no terminal was flagged, so the stage gets nothing")
        meshes = [p.GetPath().pathString
                  for p in made[0].stage().Traverse()
                  if p.GetTypeName() == "Mesh"]
        self.assertTrue(meshes, "the stage carries no geometry")


    def test_geometry_chains_onto_the_current_display_node(self):
        """Geometry chains onto the display node like a light would, through the host's own createOutputNode()."""
        panel = test_support.fixture_panel(self)    # the ISOLATED panel: its own settings, library and locations, because _protect_live_settings guarded only the settings FILE
        try:

            stage = hou.node("/stage")
            first = stage.createNode("sphere", "existing")
            current = stage.createNode("xform", "current")
            current.setFirstInput(first)
            current.setDisplayFlag(True)
            self.addCleanup(self._clear_stage)
            self.assertEqual("current", stage.displayNode().name())

            before = set(stage.children())
            panel._import_geo_in_context("/tmp/does_not_exist.bgeo", stage)
            made = [c for c in stage.children() if c not in before]
        finally:
            pass        # fixture_panel owns its own teardown

        self.assertEqual(1, len(made), "expected one new LOP")
        self.assertEqual("sopcreate", made[0].type().name())
        self.assertEqual(
            ["current"], [i.name() for i in made[0].inputs()],
            "the import did not chain onto the display node")
        self.assertEqual(
            made[0].name(), stage.displayNode().name(),
            "what you just added is not what you see")

    def _clear_stage(self):
        for child in hou.node("/stage").children():
            try:
                child.destroy()
            except hou.OperationFailed:
                pass


    def test_sop_asset_renders_a_thumbnail(self):
        self.prefs.render_on_import = 1
        geo = _sop_network("thumb_sop")
        self.model.add_asset(geo, "", "", False, name="thumbed")
        image = self._image_for(self.model.assets[-1])
        self.assertTrue(os.path.exists(image), "no SOP thumbnail written")
        rendered = QtGui.QImage(image)
        self.assertFalse(rendered.isNull())
        colours = {rendered.pixel(x, y)
                   for x in range(0, rendered.width(), 4)
                   for y in range(0, rendered.height(), 4)}
        self.assertGreater(len(colours), 1,
                           "the SOP thumbnail is a blank image")

    def test_unrenderable_context_writes_no_thumbnail(self):
        """Neither renderer is even ASKED - an absent file alone would also be produced by one that failed quietly."""
        self.prefs.render_on_import = 1
        lop = hou.node("/obj").createNode("lopnet", "thumb_lop")
        lop.createNode("sphere")
        with mock.patch.object(thumbs.ThumbNailRenderer,
                               "create_thumb_sop") as sop_render, \
                mock.patch.object(thumbs.ThumbNailRenderer,
                                  "create_thumb_cop") as cop_render:
            self.assertEqual("LOP", self.model.add_asset(
                lop, "", "", False, name="unrenderable"))
        sop_render.assert_not_called()
        cop_render.assert_not_called()
        self.assertFalse(os.path.exists(self._image_for(
            self.model.assets[-1])))

    def test_unrenderable_tile_falls_back_to_the_node_icon(self):
        """A LOP tile shows the node icon, NOT `Missing Thumbnail` - two different designed SVGs."""
        lop = hou.node("/obj").createNode("lopnet", "icon_lop")
        lop.createNode("sphere")
        self.model.add_asset(lop, "", "", False, name="icon_test")
        geo = _sop_network("icon_sop")
        self.model.add_asset(geo, "", "", False, name="rendered_test")

        node_icon = self.model._missing_thumb_image(0)
        material_missing = self.model._missing_thumb_image(1)
        if node_icon is None:  # $AMAZE unset - the SVGs cannot be found
            self.skipTest("placeholder SVGs not resolvable from $AMAZE")
        self.assertIsNotNone(material_missing)
        self.assertNotEqual(node_icon, material_missing,
                            "the LOP tile is showing Missing Thumbnail")


    def test_only_real_networks_save_their_interior(self):
        """The rule the OPmenu label must predict - `has children` would read half a scene as networks."""
        geo = _sop_network("whole_geo")
        empty = hou.node("/obj").createNode("geo", "whole_empty")
        cop = hou.node("/obj").createNode("copnet", "whole_cop")
        cop.createNode(_cop_node_type())
        light = hou.node("/obj").createNode("hlight", "whole_light")
        matnet = hou.node("/obj").createNode("matnet", "whole_matnet")

        whole = self.model.saves_whole_network
        self.assertTrue(whole(geo))
        self.assertTrue(whole(cop))
        self.assertFalse(whole(empty), "an empty network has no interior")
        self.assertFalse(whole(light), "a light is not a network")
        self.assertFalse(whole(geo.node("the_box")), "a leaf is not a network")
        self.assertFalse(whole(matnet), "materials are not this section's")

        self.assertTrue(self.model.is_container(empty))     # a DROP TARGET is the looser half: an empty geo has no interior to save but is a fine place to land
        self.assertTrue(self.model.is_container(geo))
        self.assertFalse(self.model.is_container(light))
        self.assertFalse(self.model.is_container(matnet))

    def test_cop_asset_still_renders(self):
        """The section's original behaviour, unchanged by the widening."""
        self.prefs.render_on_import = 1
        cop = hou.node("/obj").createNode("copnet", "thumb_cop")
        cop.createNode(_cop_node_type())
        self.assertEqual("COP", self.model.add_asset(
            cop, "", "", False, name="cop_thumbed"))
        image = self._image_for(self.model.assets[-1])
        self.assertTrue(os.path.exists(image), "no COP thumbnail written")
        self.assertFalse(QtGui.QImage(image).isNull())


class TheRenderDecisionHasOneHome(unittest.TestCase):
    """One method decides Cop-or-Sop, and a source scan keeps the deciders from growing back."""

    def test_the_create_verbs_are_called_only_inside_thumbs(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        callers = []
        for base, _dirs, files in os.walk(root):
            if os.path.basename(base) == "tests":
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(base, name)
                with open(path, encoding="utf-8") as handle:
                    source = handle.read()
                count = (source.count("create_thumb_sop(")
                         + source.count("create_thumb_cop("))
                if count:
                    callers.append(
                        (test_support.posix_relpath(path, root), count))
        self.assertEqual(
            ["render/thumbs.py"], [path for path, _n in callers],
            "the Cop-or-Sop decision is being made outside "
            "render_network_thumbnail again: %r" % callers)

    def _decide(self, context, thumb_node=""):
        thumber = thumbs.ThumbNailRenderer(mock.Mock())
        with mock.patch.object(
                thumbs.ThumbNailRenderer, "create_thumb_sop",
                return_value=True) as sop, \
                mock.patch.object(
                    thumbs.ThumbNailRenderer, "create_thumb_cop",
                    return_value=True) as cop:
            outcome = thumber.render_network_thumbnail(
                context, "asset1", thumb_node)
        return outcome, sop, cop

    def test_both_spellings_of_each_context_reach_one_verb(self):
        """Save reads a category name, Update Preview a renderer tag (empty for pre-context assets): one normalisation."""
        for context in ("Sop", "SOP", "sop"):
            outcome, sop, cop = self._decide(context)
            self.assertTrue(outcome, context)
            sop.assert_called_once_with("asset1")
            cop.assert_not_called()
        for context in ("Cop", "COP", ""):
            outcome, sop, cop = self._decide(context, thumb_node="wave1")
            self.assertTrue(outcome, repr(context))
            cop.assert_called_once_with("asset1", "wave1")
            sop.assert_not_called()

    def test_a_context_with_no_picture_asks_neither_verb(self):
        outcome, sop, cop = self._decide("Lop")
        self.assertIsNone(
            outcome, "a Lop network has no thumbnail render - the "
            "caller owns what that means at its door")
        sop.assert_not_called()
        cop.assert_not_called()


class TheWireSpliceReadsThePlacementFunnel(unittest.TestCase):
    """The splice asks the placement funnel, never a child diff - practice.md ▸p/nodes-section."""

    def setUp(self):
        self.net = hou.node("/obj").createNode("geo")
        self.addCleanup(self.net.destroy)
        from amaze.helpers import helpers
        helpers.forget_placed()

    def test_every_door_leaves_its_nodes_in_the_funnel(self):
        from amaze.helpers import helpers
        made = self.net.createNode("box")
        helpers.forget_placed()
        self.assertEqual([], helpers.placed_nodes(),
                         "the funnel remembered across gestures")
        helpers.place_nodes([made], hou.Vector2(1.0, 1.0))      # the creation door's form
        self.assertEqual([made], helpers.placed_nodes())
        other = self.net.createNode("sphere")       # and the no-drop-point form every import falls back to
        helpers.auto_place(other)
        self.assertEqual([other], helpers.placed_nodes(),
                         "auto placement did not report what it placed")

    def test_the_splice_calls_the_hosts_own_function(self):
        """`insertItemsIntoWire` is GUI-only, so this pins its CONTRACT headless - practice.md ▸p/nodes-section."""
        import sys
        import types
        from unittest import mock
        from amaze.core import dragengine
        a = self.net.createNode("box")
        b = self.net.createNode("merge")
        b.setInput(0, a)
        wire = b.inputConnections()[0]
        fresh = self.net.createNode("xform")
        seen = {}

        stub = types.ModuleType("nodegraphutils")
        stub.insertItemsIntoWire = (
            lambda conn, chain, every, remove_existing_connections=False:
            seen.update(conn=conn, chain=list(chain),
                        remove=remove_existing_connections))
        with mock.patch.dict(sys.modules, {"nodegraphutils": stub}):
            self.assertTrue(dragengine.splice_into_wire(wire, [fresh]))
        self.assertEqual(wire, seen.get("conn"),
                         "a different wire was spliced than the one "
                         "under the release")
        self.assertEqual([fresh], seen.get("chain"),
                         "the nodes that landed were not the ones "
                         "inserted")
        self.assertTrue(seen.get("remove"),
                        "the existing connection was left in place, "
                        "so the insert would double-wire the chain")

    def test_nothing_landed_means_nothing_is_spliced(self):
        from amaze.core import dragengine
        from amaze.helpers import helpers
        a = self.net.createNode("box")
        b = self.net.createNode("merge")
        b.setInput(0, a)
        wire = b.inputConnections()[0]
        helpers.forget_placed()
        self.assertFalse(dragengine.splice_into_wire(wire, []),
                         "an empty landing still rewired the chain")
        self.assertEqual(a, b.inputs()[0], "the chain was disturbed")


class AutoPlacementLeavesTheSceneAlone(unittest.TestCase):
    """A drop must rearrange nothing, so placement goes through ONE helper carrying the no-move flags."""

    def setUp(self):
        self.net = hou.node("/obj").createNode("geo")
        self.addCleanup(self.net.destroy)

    def _others(self):
        a = self.net.createNode("box")
        b = self.net.createNode("sphere")
        a.setPosition(hou.Vector2(0.0, 0.0))
        b.setPosition(hou.Vector2(0.4, -0.2))
        return a, b

    def test_placing_a_node_never_moves_the_artists_nodes(self):
        from amaze.helpers import helpers
        a, b = self._others()
        before = [tuple(n.position()) for n in (a, b)]
        fresh = self.net.createNode("merge")
        fresh.setInput(0, a)
        helpers.auto_place(fresh)
        after = [tuple(n.position()) for n in (a, b)]
        self.assertEqual(before, after,
                         "auto placement rearranged the network - the "
                         "nodes the artist placed moved")

    def test_the_app_never_calls_the_rearranging_form(self):
        """A raw moveToGoodPosition() carries the defaults that move other nodes, so the app calls it in one place."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        offenders = []
        for base, _dirs, files in os.walk(root):
            if os.path.basename(base) == "tests":
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(base, name)
                with open(path, encoding="utf-8") as handle:
                    body = handle.read()
                if ".moveToGoodPosition(" in body:
                    offenders.append(test_support.posix_relpath(path, root))
        self.assertEqual(
            ["helpers/helpers.py"], offenders,
            "these call Houdini's rearranging placement directly - "
            "helpers.auto_place is the one home: %r" % offenders)


class PlaceNodesTest(unittest.TestCase):
    """The ONE placement rule: the group's centroid lands at the position, relative layout preserved."""

    def test_the_group_moves_preserving_layout(self):
        from amaze.helpers import helpers

        net = hou.node("/obj").createNode("geo")
        self.addCleanup(net.destroy)
        first = net.createNode("null")
        first.setPosition(hou.Vector2(0.0, 0.0))
        second = net.createNode("null")
        second.setPosition(hou.Vector2(2.0, 1.0))
        helpers.place_nodes([first, second], hou.Vector2(10.0, 10.0))
        self.assertAlmostEqual(
            2.0, second.position().x() - first.position().x(),
            msg="the relative layout was not preserved")
        self.assertAlmostEqual(
            1.0, second.position().y() - first.position().y())
        half = helpers.centred_on(hou.Vector2(0.0, 0.0))    # setPosition sets a node's CORNER and the host subtracts getNewNodeHalfSize() at the mouse - practice.md ▸p/nodes-section
        centroid_x = (first.position().x() + second.position().x()) / 2
        centroid_y = (first.position().y() + second.position().y()) / 2
        self.assertAlmostEqual(10.0 + half.x(), centroid_x)
        self.assertAlmostEqual(10.0 + half.y(), centroid_y)

    def test_no_position_is_a_no_op(self):
        from amaze.helpers import helpers

        net = hou.node("/obj").createNode("geo")
        self.addCleanup(net.destroy)
        node = net.createNode("null")
        node.setPosition(hou.Vector2(3.0, -1.0))
        helpers.place_nodes([node], None)
        self.assertAlmostEqual(3.0, node.position().x())
        self.assertAlmostEqual(-1.0, node.position().y())


if __name__ == "__main__":
    unittest.main()
