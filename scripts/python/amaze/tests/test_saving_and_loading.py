"""Saving and loading: one test per requirement in docs/requirements/saving-and-loading.md."""

import os
import shutil
import types
import unittest
from unittest import mock

from PySide6 import QtWidgets

import hou

from amaze import messages
from amaze.actions import materials as material_actions, nodes as node_actions
from amaze.core import asset_record, guard, library, library_db, library_files, library_settings
from amaze.core import cop_library, material
from amaze.pane import asks, pane as pane_mod
from amaze.prefs import prefs as prefs_mod
from amaze.render import nodes, thumbs
from amaze.tests import faults, test_support
from amaze.utils import rc_calls

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

MATERIALS = library_files.MATERIALS
state = test_support.library_state


def read(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def scene() -> set:
    return {node.path() for node in hou.node("/").allSubChildren()}


def digest(node) -> list:
    """Every node under `node`, its inputs and the raw value of each parm."""
    return [(each.path(), [str(wire) for wire in each.inputs()],
             [(parm.name(), str(parm.rawValue())) for parm in each.parms()])
            for each in [node] + list(node.allSubChildren())]


class Accepting(asks.Asks):
    """The window a pane engine is shown in, accepting each Save dialog as it opens."""

    def open_save(self, question, then) -> None:
        then(asks.SaveAnswer(question.section, question.name, "", "", False, ""))


class SavingTest(unittest.TestCase):
    """A fixture library, and a Karma material reading a texture and a COP network in the scene."""

    def setUp(self):
        test_support.pin_env(self, "OCIO", "/dev/null")    # the save checks it; nothing renders
        self.addCleanup(test_support.reset_database_singletons)
        self.fresh()
        folder = test_support.scratch_dir("amaze_sl_texture_")
        self.addCleanup(shutil.rmtree, folder, True)
        self.texture = test_support.put(folder, "brick.png", b"brick")
        with hou.undos.disabler():
            self.cops = hou.node("/obj").createNode("copnet", "sl_cops")
            self.plate = self.cops.createNode("constant", "plate")
        self.addCleanup(test_support.drop_node, self.cops)
        self.node = self.karma("sl_brick")
        self.changes = 0

    def fresh(self) -> None:
        """A new library and its model, as a session that just opened it."""
        test_support.reset_database_singletons()
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.render_on_import = 0
        self.model = library.MaterialLibrary(preferences=self.prefs)

    def karma(self, name: str):
        def produce(builder):
            surface = builder.createNode("mtlxstandard_surface", "surface")
            surface.parm("specular_roughness").set(0.321)
            builder.createNode("mtlximage", "texture").parm("file").set(self.texture)
            builder.createNode("mtlximage", "plate").parm("file").set("op:" + self.plate.path())
            return surface
        with hou.undos.disabler():
            made = nodes.build_karma_material(hou.node("/mat"), name, produce).builder
        self.addCleanup(test_support.drop_node, made)
        return made

    def add(self):
        return material_actions.add_asset(self.model, self.node, "", "", False)

    def saved(self) -> tuple:
        """(the id, the row, the files) of the asset the scene node was saved as."""
        asset_id = self.node.userData("assetlib_id")
        return (asset_id, self.model.find_asset_row_by_id(asset_id),
                self.model.asset_files(asset_id))

    def save_over(self):
        return material_actions.update_asset_content(self.model, self.saved()[1], self.node)

    def change(self) -> None:
        """A value, a builder control and the COP network changed in the scene."""
        self.changes += 1
        group = self.node.parmTemplateGroup()
        group.append(hou.FloatParmTemplate("control%d" % self.changes, "Control", 1))
        self.node.setParmTemplateGroup(group)
        self.node.node("surface").parm("specular_roughness").set(0.5 / self.changes)
        self.cops.createNode("constant", "extra%d" % self.changes)

    def rows(self) -> set:
        return set(library_db.guard_of(self.prefs).read(MATERIALS).document["assets"])

    def imported(self, **where) -> hou.Node:
        """The saved asset loaded into the scene."""
        _id, row, _files = self.saved()
        ok, reason, created = material_actions.import_asset_to_scene(
            self.model, self.model.index(row, 0), **where)
        for made in created:
            self.addCleanup(test_support.drop_node, made)
        self.assertTrue(ok, reason)
        return created[0]

    def arrived(self, disk) -> tuple:
        """(new rows, new files with each new id spelled <id>) once a save ran on `disk`."""
        self.fresh()
        rows, files = self.rows(), set(state(self.prefs.dir))
        library_db.guard_of(self.prefs).disk = disk
        try:
            self.add()
        except faults.Cut:
            pass
        faults.crash(self.prefs)
        added = self.rows() - rows
        found = set(state(self.prefs.dir)) - files
        for asset_id in added:
            found = {path.replace(asset_id, "<id>") for path in found}
        return len(added), found

    def test_sl01_a_new_asset_is_saved_whole_or_leaves_nothing(self):
        counting = faults.FaultDisk()
        whole = self.arrived(counting)
        own = "materials/sl_brick__<id>/"
        self.assertEqual((1, {own + "<id>.mat", own + "<id>.json", own + "<id>_cop.mat",
                              own + "textures/brick.png"}), whole)
        for step in range(1, counting.steps + 1):
            self.assertIn(self.arrived(faults.FaultDisk(cut_at=step)), ((0, set()), whole), step)
        self.fresh()
        before, folders = state(self.prefs.dir), sorted(os.listdir(
            material.section_folder(self.prefs.dir, MATERIALS)))
        real, calls = nodes.hda_fallbacks_needed, []

        def fails_at_the_network(items):
            calls.append(items)
            if len(calls) == 2:    # the COP network was written, the network's own file fails
                raise hou.OperationFailed("the disk went away")
            return real(items)
        with mock.patch.object(nodes, "hda_fallbacks_needed", fails_at_the_network):
            with self.assertRaises(hou.OperationFailed):
                self.add()
        library_db.guard_of(self.prefs).disk = faults.FaultDisk(full_from=1)
        self.assertEqual("", self.add())
        self.assertEqual((before, folders), (state(self.prefs.dir), sorted(os.listdir(
            material.section_folder(self.prefs.dir, MATERIALS)))))

    def test_sl02_a_save_over_replaces_network_record_and_cop_together_or_not_at_all(self):
        def unchanged(disk) -> list:
            self.fresh()
            self.assertTrue(library_settings.set_allow_overwrite(self.prefs, False))    # VS's part
            self.add()
            own = self.saved()[2]
            parts = (lambda: (read(own["mat"]), read(own["cop"]),
                              asset_record.read(own["json"])[asset_record.BUILDER]))
            old = parts()
            self.change()
            library_db.guard_of(self.prefs).disk = disk
            try:
                self.save_over()
            except (faults.Cut, OSError):
                pass
            faults.crash(self.prefs)
            return [now == was for now, was in zip(parts(), old)]
        counting = faults.FaultDisk()
        self.assertEqual([False] * 3, unchanged(counting))
        for step in range(1, counting.steps + 1):
            self.assertIn(unchanged(faults.FaultDisk(cut_at=step)), ([False] * 3, [True] * 3), step)
        self.assertEqual([True] * 3, unchanged(faults.FaultDisk(full_from=1)))
        self.assertEqual([], [name for _here, _dirs, names in os.walk(self.prefs.dir)
                              for name in names if name.endswith(guard.SCRATCH)])

    def test_sl03_a_save_over_is_refused_when_another_session_changed_the_network(self):
        self.add()
        own = self.saved()[2]
        theirs = b"the network another session saved"
        with open(own["mat"], "wb") as handle:
            handle.write(theirs)
        self.change()
        with self.assertRaises(material_actions.UpdateRefused) as refused:
            self.save_over()
        self.assertEqual(messages.UPDATE_REFUSED_CHANGED_ON_DISK, str(refused.exception))
        self.assertEqual(theirs, read(own["mat"]))

    def test_sl04_an_unreadable_record_is_never_written_over(self):
        self.add()
        asset_id, _row, own = self.saved()
        broken = read(own["json"])[:20]
        with open(own["json"], "wb") as handle:
            handle.write(broken)
        self.change()
        with self.assertRaises(OSError):
            self.save_over()
        library_db.document(self.prefs, MATERIALS).edit("assets", asset_id, tags=["edited"])
        library_db.flush(self.prefs)
        self.assertEqual(broken, read(own["json"]))

    def test_sl10_saving_leaves_the_scene_as_it_was(self):
        patch = mock.patch.object(prefs_mod.Prefs, "save")    # the settings stay as set here
        patch.start()
        self.addCleanup(patch.stop)
        pane = pane_mod.Pane(Accepting())
        pane.prefs.dir = test_support.with_fixture_user(test_support.fresh_library(self))
        pane.prefs.library_user, pane.prefs.render_on_import = test_support.FIXTURE_USER, 0
        self.assertTrue(pane.library.open_library())
        hou.clearAllSelected()
        self.cops.setSelected(True)
        before, held = digest(self.node), test_support.asset_ids(pane.material_model)
        hou.undos.clear()
        self.addCleanup(hou.undos.clear)
        with mock.patch.object(rc_calls, "start"), mock.patch.object(
                rc_calls, "_find_panel", return_value=types.SimpleNamespace(pane=pane)):
            rc_calls.save(self.node)
        self.assertEqual(1, len(test_support.arrived(pane.material_model, held)))
        self.maxDiff = None
        self.assertEqual(([self.cops], before, ()), (
            list(hou.selectedNodes()), digest(self.node), hou.undos.undoLabels()))

    def test_sl11_an_import_carries_its_assets_id_and_the_nodes_inside_carry_none(self):
        self.node.node("surface").setUserData("assetlib_id", "an_older_asset")
        self.add()
        asset_id = self.saved()[0]
        self.assertNotIn(asset_id, ("", None, "an_older_asset"))
        loaded = self.imported(target="mat")
        self.assertEqual((asset_id, []), (loaded.userData("assetlib_id"), [
            node.path() for node in loaded.allSubChildren() if node.userData("assetlib_id")]))

    def test_sl12_a_failed_import_leaves_the_scene_as_it_was(self):
        self.add()
        _id, row, own = self.saved()
        with open(own["mat"], "wb") as handle:
            handle.write(b"no network Houdini can load")
        with hou.undos.disabler():
            library_node = hou.node("/stage").createNode("materiallibrary", "sl_library")
            geometry = hou.node("/obj").createNode("geo", "sl_geometry")
        for made in (library_node, geometry):
            self.addCleanup(test_support.drop_node, made)
        for context in (library_node, geometry):
            before = scene()
            ok, _reason, created = material_actions.import_asset_to_scene(
                self.model, self.model.index(row, 0), context_node=context)
            self.assertEqual((False, [], before), (ok, created, scene()), context.path())

    def test_sl20_a_saved_material_loads_back_as_it_was_saved(self):
        surface = self.node.node("surface")
        surface.parm("metalness").setExpression("0.25 + 0.5", hou.exprLanguage.Hscript)
        for frame, value in ((1, 1.2), (24, 1.8)):
            key = hou.Keyframe()
            key.setFrame(frame)
            key.setValue(value)
            surface.parm("specular_IOR").setKeyframe(key)
        self.change()
        self.node.parm("control1").set(0.75)
        self.add()
        loaded = self.imported(target="mat")
        self.assertEqual(sorted(child.name() for child in self.node.children()),
                         sorted(child.name() for child in loaded.children()))
        again = loaded.node("surface")
        self.assertEqual(("0.25 + 0.5", [1.2, 1.8], 0.75, True), (
            again.parm("metalness").expression(),
            [key.value() for key in again.parm("specular_IOR").keyframes()],
            loaded.parm("control1").eval(), nodes.surface_terminal_wired(loaded)))
        self.assertAlmostEqual(0.5, again.parm("specular_roughness").eval())

    def test_sl21_a_node_setup_loads_back_with_its_notes_boxes_and_dots(self):
        model = cop_library.CopLibrary(preferences=self.prefs)
        with hou.undos.disabler():
            setup = hou.node("/obj").createNode("geo", "sl_setup")
            box = setup.createNode("box", "the_box")
            mountain = setup.createNode("mountain", "the_mountain")
            dot = setup.createNetworkDot()
            dot.setInput(box)
            mountain.setInput(0, dot)
            mountain.setPosition(box.position() + hou.Vector2(5.0, -3.0))
            setup.createStickyNote()
            setup.createNetworkBox().addItem(box)
        self.addCleanup(test_support.drop_node, setup)
        self.assertEqual("SOP", node_actions.add_asset(model, setup, "", "", False))
        loose = hou.node("/obj").createNode("geo", "sl_loose")
        self.addCleanup(test_support.drop_node, loose)
        for where in (loose, hou.node("/obj")):
            ok, reason, created = node_actions.import_asset_to_scene(
                model, model.index(model.find_asset_row_by_id(setup.userData("assetlib_id")), 0),
                context_node=where)
            self.assertTrue(ok, reason)
            held = created[0].parent() if where == loose else created[0]
            if where != loose:
                self.addCleanup(test_support.drop_node, held)
            again = {node.name().rstrip("0123456789"): node for node in held.children()}
            self.assertEqual((again["the_box"], hou.Vector2(5.0, -3.0), 1, 1, 1), (
                again["the_mountain"].input(0),
                again["the_mountain"].position() - again["the_box"].position(),
                len(held.networkDots()), len(held.stickyNotes()), len(held.networkBoxes())))

    def test_sl22_a_cop_network_loads_beside_its_material_and_goes_when_unused(self):
        self.add()
        loaded = self.imported(target="mat")
        companion = hou.node(loaded.node("plate").parm("file").eval()[len("op:"):]).parent()
        self.addCleanup(test_support.drop_node, companion)
        self.assertEqual(("/obj", False), (companion.parent().path(), companion == self.cops))
        self.node.node("plate").destroy()
        cop = self.saved()[2]["cop"]
        self.assertTrue(self.save_over())
        self.assertFalse(os.path.exists(cop))

    def test_sl23_a_loaded_materials_textures_point_into_its_own_folder(self):
        self.add()
        own = os.path.dirname(self.saved()[2]["mat"])
        self.prefs.path_style = "job"    # Write Paths As
        self.addCleanup(hou.putenv, "JOB", hou.getenv("JOB") or "")
        hou.putenv("JOB", os.path.dirname(os.path.normpath(self.prefs.dir)))
        raw = self.imported(target="mat").node("texture").parm("file").unexpandedString()
        self.assertTrue(raw.startswith("$JOB/"), raw)
        self.assertEqual(os.path.realpath(os.path.join(own, "textures", "brick.png")),
                         os.path.realpath(hou.text.expandString(raw)))

    def test_sl24_an_import_that_cannot_work_says_why_and_makes_nothing(self):
        self.add()
        _id, row, own = self.saved()
        asset = self.model.assets[row]

        def refused(why: str) -> None:
            before = scene()
            ok, reason, created = material_actions.import_asset_to_scene(
                self.model, self.model.index(row, 0), target="mat")
            self.assertEqual((False, [], before), (ok, created, scene()))
            self.assertIn(why, str(reason))
        test_support.write_section(own["json"], asset_record.BUILDER, {
            "type": "a_builder_no_plugin_here", "interface": "", "values": {}})
        refused("a_builder_no_plugin_here")
        with open(own["mat"], "wb"):
            pass
        refused("empty")
        os.remove(own["mat"])
        refused("could not be read")
        asset._mat_id = "../../outside"    # an id read from a database another program wrote
        refused("its id")

    def test_sl26_a_picture_that_fails_to_render_costs_only_the_picture(self):
        self.prefs.render_on_import = 1
        with mock.patch.object(thumbs.ThumbNailRenderer, "create_thumb",
                               side_effect=hou.OperationFailed("the render stopped")):
            self.assertTrue(self.add())
        asset_id, _row, own = self.saved()
        self.assertIn(asset_id, self.rows())
        self.assertTrue(os.path.isfile(own["mat"]))


if __name__ == "__main__":
    unittest.main()
