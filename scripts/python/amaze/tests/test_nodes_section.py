"""The Nodes section: saving and reloading node networks from ANY
Houdini context, not just Copernicus.

The section began as COP-only and was widened in place - which is why
the context lives in the asset's existing `renderer` field, holding the
literal "COP" for everything saved before. These tests pin the three
promises that widening has to keep:

  * the context is read from the network that CONTAINS the nodes, so a
    selection and its whole network agree ("Sop" either way);
  * an asset returns to a network of its own kind, with its nodes and
    their connections intact;
  * an asset REFUSES a foreign context rather than half-creating a
    network of nodes that cannot exist there - the failure mode that
    would leave debris in a user's scene.

Plus the thumbnail routing, which is the visible half: SOP renders the
geometry, COP renders the image, and anything else deliberately renders
nothing so the tile falls back to the node icon.

Real files, real networks, fixture library (never the live one).
"""

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

# THREE dirnames: tests/ -> amaze/ -> python/. See test_roundtrip.py -
# four lands on scripts/, where the tests import the INSTALL instead.
sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import cop_library  # noqa: E402
from amaze.render import thumbs  # noqa: E402
from amaze.tests import test_support  # noqa: E402


def _sop_network(name: str) -> hou.Node:
    """A geo with two CONNECTED nodes - the connection is half of what
    the round-trip has to preserve."""
    geo = hou.node("/obj").createNode("geo", name)
    box = geo.createNode("box", "the_box")
    mountain = geo.createNode("mountain", "the_mountain")
    mountain.setFirstInput(box)
    mountain.setDisplayFlag(True)
    return geo


def _cop_node_type() -> str:
    """Whatever this Houdini build calls a simple COP - node type names
    moved with Copernicus, so the test asks rather than assumes."""
    kinds = hou.copNodeTypeCategory().nodeTypes()
    for wanted in ("ramp", "gradient", "color", "constant", "noise"):
        if wanted in kinds:
            return wanted
    return sorted(kinds)[0]


class NodesSectionTest(unittest.TestCase):

    def setUp(self):
        # Connectors are cached per FILENAME, so without this every test
        # after the first reads the previous test's cops.json.
        test_support.reset_database_singletons()
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

    # -- context detection ------------------------------------------

    def test_context_of_reads_the_containing_network(self):
        geo = _sop_network("ctx_sop")
        cop = hou.node("/obj").createNode("copnet", "ctx_cop")
        lop = hou.node("/obj").createNode("lopnet", "ctx_lop")
        self.assertEqual("Sop", self.model.context_of(geo))
        self.assertEqual("Cop", self.model.context_of(cop))
        self.assertEqual("Lop", self.model.context_of(lop))

    def test_context_of_selection_matches_its_network(self):
        """A selection is described by where it LIVES, not by itself -
        node.parent() when items are given. Get this backwards and a
        selection of SOPs reports the /obj context that holds the geo."""
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

    # -- round trip --------------------------------------------------

    def test_the_import_seam_returns_what_it_created(self):
        """(ok, reason, created): the import hands back the nodes it
        added, and helpers.place_nodes - the one placement rule -
        moves them as a group to a release point. The seam every
        drop-position behaviour rides; no caller diffs children."""
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
        xs = [n.position().x() for n in created]
        ys = [n.position().y() for n in created]
        self.assertAlmostEqual(spot.x(), sum(xs) / len(xs),
                               msg="the group centroid missed the spot")
        self.assertAlmostEqual(spot.y(), sum(ys) / len(ys))

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
        # A selection is passed as one of the SELECTED items, not the
        # container - the network is reached through its parent.
        self.assertEqual("SOP", self.model.add_asset(
            box, "", "", False, items=[box], name="sel_one"))
        geo.destroy()

        dest = hou.node("/obj").createNode("geo", "sel_dest")
        ok, reason, _created = self.model.import_asset_to_scene(
            self.model.index(0, 0), context_node=dest)
        self.assertTrue(ok, reason)
        self.assertEqual(["the_box"], [n.name() for n in dest.children()])

    # -- the refusal -------------------------------------------------

    def test_a_foreign_context_gets_a_container_where_one_exists(self):
        """A Copernicus network CAN hold SOPs - in a sopnet - and
        refusing there while accepting the identical nodes saved from a
        sopnet was incoherent. So this builds one rather than refusing."""
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
        """The refusal has to survive the widening, or the guard is
        gone: a material network has no home for SOPs at any depth, and
        half-creating one is worse than saying so."""
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

    # -- landing at object level -------------------------------------

    def _import_into(self, name, dest):
        """Save-free helper: import the asset called `name` into dest,
        returning (ok, reason, the nodes it created there)."""
        row = [i for i, a in enumerate(self.model.assets) if a.name == name][0]
        before = set(dest.children())
        ok, reason, _created = self.model.import_asset_to_scene(
            self.model.index(row, 0), context_node=dest)
        return ok, reason, [c for c in dest.children() if c not in before]

    def test_a_network_asset_lands_at_object_level_in_its_container(self):
        """Reported from a live session: assets saved at object level
        could not be recreated there, while /stage worked.

        /obj is not a SOP network, so an exact-context rule refuses
        everything there - but building the container IS the answer at
        object level, not the failure case. Every context that has a
        home in /obj must get one."""
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
        """The trap a plain can-I-create-it test walks into: every
        context has a `subnet`, so a SOP subnet looks like a home for
        object-level nodes and is not one."""
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

    # -- where a network is allowed to land --------------------------

    def test_every_destination_and_context_pairing(self):
        """The whole matrix, because the rule is only trustworthy if it
        holds everywhere - and because the first version of it, which
        asked the registry for ANY type that could hold the context,
        answered /stage+SOP with `copytopoints` and a geo+SOP with a
        third-party LYNX HDA."""
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
            # Solaris hosts SOPs in a SOP Create - the node that turns
            # geometry into USD. A bare sopnet there is invisible to
            # the stage.
            ("/stage", "Sop"): "sopcreate",
            ("/stage", "Cop"): "copnet",
            ("/stage", "Lop"): "lopnet",
            ("/stage", "Object"): None,
            ("geo", "Cop"): "copnet",
            # LOP nodes dropped in a SOP network get a LOP network.
            ("geo", "Lop"): "lopnet",
            ("geo", "Object"): None,
            ("copnet", "Sop"): "sopnet",
            ("lopnet", "Sop"): "sopcreate",
            # Materials are the material section's business.
            ("matnet", "Sop"): None,
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

        # The SOPs go where the HDA SAYS they go: its DiveTarget and
        # EditableNodes both read "sopnet/create", two levels down. The
        # first version stopped at `sopnet` - one level too high, beside
        # the machinery - and OUT's input is `create`, so the stage got
        # empty geometry. Reported live: "not as it should".
        target = self.model.load_target_in(made[0], "Sop")
        self.assertEqual("sopnet/create", target.path().split(
            made[0].path() + "/")[-1])
        landed = {n.name() for n in target.children()}
        self.assertIn("the_box", landed)
        self.assertIn("the_mountain", landed)
        self.assertEqual(
            "the_box",
            target.node("the_mountain").inputs()[0].name(),
            "the connection did not survive the trip into Solaris")

        # The asset must stay LOCKED. Unlocking it to write was both
        # unnecessary (the editable node accepts writes while locked)
        # and the reason a double-click showed sopimport/sopnet/xform
        # instead of the user's own SOPs.
        self.assertTrue(made[0].matchesCurrentDefinition(),
                        "the SOP Create was unlocked - diving will show "
                        "its internals instead of the imported nodes")

        # And the wrapper only shows what its output carries: the
        # terminal node must be display-flagged or the stage is empty.
        flagged = [n.name() for n in target.children()
                   if n.isDisplayFlagSet()]
        self.assertEqual(["the_mountain"], flagged)
        meshes = [p.GetPath().pathString for p in made[0].stage().Traverse()
                  if p.GetTypeName() == "Mesh"]
        self.assertTrue(meshes, "the stage carries no geometry")

    def test_an_unflagged_network_still_reaches_the_stage(self):
        """The archive usually carries a display flag, so the fallback
        that sets one is invisible - until a save whose nodes had none.
        Then the SOP Create's editable subnet outputs nothing and the
        stage is empty, which is the exact symptom this fixes."""
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

    # -- geometry into Solaris ---------------------------------------

    def test_geometry_chains_onto_the_current_display_node(self):
        """Dropping geometry into a Solaris stage should behave like
        adding a light or a render node: wired onto the current tree,
        and displayed. Houdini's own createOutputNode() does that - the
        built-in its tab menu uses - rather than a hand-rolled
        setFirstInput + flag dance.

        Uses the REAL panel: the method reaches enough of it that a stub
        only proves the stub works."""
        # The ISOLATED panel: its own settings, library and file
        # locations. _protect_live_settings only guarded the settings
        # FILE - the panel still opened the machine's real library and
        # its real registered folders.
        panel = test_support.fixture_panel(self)
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

    # -- thumbnail routing -------------------------------------------

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
        """LOP (and Dop, Top...) have nothing to render as a picture -
        the tile is meant to fall back to the node icon, which only
        happens if no image file exists.

        Asserting the file is absent is not enough on its own: a
        renderer that IS called and quietly fails leaves no file either.
        So the renderers are watched - the promise is that neither is
        even asked."""
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
        """A LOP asset's tile shows the node icon, NOT the "Missing
        Thumbnail" graphic - nothing failed, there is simply no picture
        to take. Two different designed SVGs, so the images differ."""
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

    # -- which nodes save as a whole network -------------------------

    def test_only_real_networks_save_their_interior(self):
        """The rule the OPmenu label has to predict. A light carries 33
        internal SOPs and a camera 3, so "has children" would read half
        the objects in a scene as networks."""
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

        # Being a DROP TARGET is the looser half of the same rule: an
        # empty geo has no interior to save but is a fine place to land.
        self.assertTrue(self.model.is_container(empty))
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


if __name__ == "__main__":
    unittest.main()




class TheRenderDecisionHasOneHome(unittest.TestCase):
    """The Cop-or-Sop thumbnail decision was typed twice - once at
    save (render/nodes.py) and once at Update Preview
    (core/cop_library.py) - the two-resolvers shape that produced the
    wrangle double-click bug. One method decides now, and a source
    scan keeps the deciders from growing back."""

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
                    callers.append((os.path.relpath(path, root), count))
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
        """The save side reads a category name (Sop, Cop); Update
        Preview reads a renderer tag (SOP, COP, and empty for assets
        saved before contexts were recorded). One normalisation."""
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
    """Dropping onto a wire inserts what landed into that chain.

    Reported live: the wire highlighted but nothing was inserted -
    the splice had been wired into the CREATION door only, while a
    node or material payload lands through its own import door. What
    every door DOES share is the placement funnel, so the splice asks
    that instead of diffing a network's children (the child-diff
    version of this was withdrawn once already - practice.md ▸ DONT
    PATCH, DONT HAND-ROLL)."""

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
        # The creation door's form...
        helpers.place_nodes([made], hou.Vector2(1.0, 1.0))
        self.assertEqual([made], helpers.placed_nodes())
        # ...and the no-drop-point form every import falls back to.
        other = self.net.createNode("sphere")
        helpers.auto_place(other)
        self.assertEqual([other], helpers.placed_nodes(),
                         "auto placement did not report what it placed")

    def test_the_splice_calls_the_hosts_own_function(self):
        """The rewiring is SideFX's, not ours: `insertItemsIntoWire`
        reads the wire's four facts and handles chains, dots and
        network boxes. It is GUI-only - the module touches
        `hou.ui.colorFromName` at import, like `lop_dragdrop.py`
        (research.md) - so this pins the CONTRACT headless: the right
        connection, the landed nodes, and the flag that removes the
        existing connections. The rewiring itself was proven in a
        live session (2026-08-07): a null dropped on a wire ended up
        between the two nodes, and the downstream one read from it.
        """
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
    """Reported live: a drop rearranged the network - other nodes
    slid away from where the artist had put them.

    Measured on real nodes (2026-08-07): `moveToGoodPosition()` with
    its defaults moved an unrelated box from y=0.0 to y=0.894 and a
    sphere with it; the same call with `move_inputs`/`move_outputs`/
    `move_unconnected` all False left both untouched. Houdini's own
    tab-menu flow places the new node and rearranges nothing, so
    Amaze places through ONE helper that carries those flags."""

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
        """A raw moveToGoodPosition() carries the defaults that move
        other nodes, so the app calls it in exactly one place."""
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
                    offenders.append(os.path.relpath(path, root))
        self.assertEqual(
            ["helpers/helpers.py"], offenders,
            "these call Houdini's rearranging placement directly - "
            "helpers.auto_place is the one home: %r" % offenders)


class PlaceNodesTest(unittest.TestCase):
    """The ONE placement rule: created nodes move as a group so their
    centroid lands at the position, relative layout preserved; no
    position means the creator's own placement stands."""

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
        centroid_x = (first.position().x() + second.position().x()) / 2
        centroid_y = (first.position().y() + second.position().y()) / 2
        self.assertAlmostEqual(10.0, centroid_x)
        self.assertAlmostEqual(10.0, centroid_y)

    def test_no_position_is_a_no_op(self):
        from amaze.helpers import helpers

        net = hou.node("/obj").createNode("geo")
        self.addCleanup(net.destroy)
        node = net.createNode("null")
        node.setPosition(hou.Vector2(3.0, -1.0))
        helpers.place_nodes([node], None)
        self.assertAlmostEqual(3.0, node.position().x())
        self.assertAlmostEqual(-1.0, node.position().y())
