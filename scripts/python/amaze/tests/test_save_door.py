"""One `Save to Amaze` door: what it offers, which it opens on. ▸p/save-section-row"""

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

from amaze.actions import nodes as node_actions  # noqa: E402
from amaze.dialogs import code_dialog, save_dialog  # noqa: E402
from amaze.panel import sections  # noqa: E402
from amaze.tests import test_support  # noqa: E402


def _material(test, name="door_mtl"):
    node = hou.node("/mat").createNode("subnet", name)
    node.createNode("mtlxstandard_surface", "surf")
    test.addCleanup(node.destroy)
    return node


def _geo(test, name="door_geo"):
    geo = hou.node("/obj").createNode("geo", name)
    test.addCleanup(geo.destroy)
    return geo


def _wrangle(test):
    wrangle = _geo(test, "door_wrangle_geo").createNode(
        "attribwrangle", "door_wrangle")
    wrangle.parm("snippet").set("@Cd = 1;")
    return wrangle


def _ramp_node(test):
    null = _geo(test, "door_ramp_geo").createNode("null", "door_ramp")
    group = null.parmTemplateGroup()
    group.append(hou.RampParmTemplate("tint", "Tint",
                                      hou.rampParmType.Color))
    null.setParmTemplateGroup(group)
    return null


def _choosing(section_key, language=""):
    """A real D09 whose exec picks `section_key` and presses OK."""
    def fake_exec(dialog):
        dialog.combo_section.setCurrentIndex(
            dialog._section_keys.index(section_key))
        if language:
            dialog.combo_language.setCurrentText(language)
        dialog._on_accept()
        return 1
    return mock.patch.object(save_dialog.SaveDialog, "exec", fake_exec)


class TheDoorOffersWhatCanTakeTheNode(unittest.TestCase):

    def setUp(self):
        self.panel = test_support.fixture_panel(self)

    def test_the_door_offers_what_can_take_the_selection(self):
        """A multi-selection never offers a one-node section, and an empty wrangle no Code."""
        wrangle = _wrangle(self)

        def emptied():
            wrangle.parm("snippet").set("   ")
            return [wrangle]

        for why, nodes, offered, refused in (
                ("a material", lambda: [_material(self)],
                 {"material", "cop"}, {"code"}),
                ("a wrangle", lambda: [wrangle], {"code", "cop"}, {"material"}),
                ("a ramp node", lambda: [_ramp_node(self)], {"gradient"}, set()),
                ("two materials",
                 lambda: [_material(self, "m1"), _material(self, "m2")],
                 {"material"}, {"gradient", "code"}),
                ("an empty wrangle", emptied, set(), {"code"})):
            with self.subTest(why):
                keys = set(self.panel._save_targets(nodes()))
                self.assertEqual(set(), offered - keys,
                                 "%s is not offered these" % why)
                self.assertEqual(set(), refused & keys,
                                 "%s is offered these" % why)


class TheDoorOpensOnTheLikeliestSection(unittest.TestCase):

    def test_the_door_opens_on_the_likeliest_section(self):
        """The open section wins only when it can take the node."""
        sub = hou.node("/obj").createNode("subnet", "door_obj_subnet")
        self.addCleanup(sub.destroy)
        wrangle = _wrangle(self)
        for why, keys, nodes, prefer, expected in (
                ("a material in /mat", ["material", "cop"], [_material(self)],
                 "", "material"),
                ("a subnet outside a material network", ["material", "cop"],
                 [sub], "", "cop"),
                ("a wrangle", ["code", "cop"], [wrangle], "", "code"),
                ("the open section", ["code", "cop"], [wrangle], "cop", "cop"),
                ("a section that cannot take it", ["code", "cop"], [wrangle],
                 "file", "code")):
            with self.subTest(why):
                self.assertEqual(expected,
                                 sections.save_guess(keys, nodes, prefer=prefer))


class TheSectionRowDrivesTheRestOfTheDialog(unittest.TestCase):

    def _dialog(self, section="material"):
        offers = {"material": (["Metal", "Wood"], "Wood"),
                  "code": (["Toolbox"], "Toolbox")}
        dialog = save_dialog.SaveDialog(
            *offers[section], name="n",
            sections=(("material", "Material"), ("code", "Code")),
            section=section, categories_for=offers.get,
            language="OpenCL", language_sections=("code",))
        self.addCleanup(dialog.deleteLater)
        return dialog

    def _cats(self, dialog):
        combo = dialog.combo_cats
        return [combo.itemText(i) for i in range(combo.count())]

    def test_changing_section_swaps_the_categories_and_keeps_the_name(self):
        dialog = self._dialog()
        dialog.line_name.setText("typed")
        dialog.combo_section.setCurrentIndex(1)
        self.assertEqual(["Toolbox"], self._cats(dialog))
        self.assertEqual("code", dialog.section)
        dialog._on_accept()
        self.assertEqual("typed", dialog.name)

    def test_language_is_live_only_for_code(self):
        """Greyed for a material, where it is nobody's answer; live for code."""
        greyed = self._dialog()
        self.assertFalse(greyed.combo_language.isEnabled())
        greyed._on_accept()
        self.assertEqual("", greyed.language)
        dialog = self._dialog()
        dialog.combo_section.setCurrentIndex(1)
        self.assertTrue(dialog.combo_language.isEnabled())
        self.assertEqual("OpenCL", dialog.combo_language.currentText())


class TheChosenSectionIsWhereTheSaveLands(unittest.TestCase):

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.panel.prefs.render_on_import = 0

    def test_a_material_saved_to_node_comes_back_in_a_material_library(self):
        node = _material(self, "door_to_node")
        before = self.panel.cop_model.rowCount()
        held = test_support.asset_ids(self.panel.cop_model)
        with _choosing("cop"):
            self.panel._save_new([node], "material", node)
        self.assertEqual(before + 1, self.panel.cop_model.rowCount(),
                         "the save did not land in Node")
        asset, = test_support.arrived(self.panel.cop_model, held)
        self.assertEqual("VOP", asset.renderer)
        index = self.panel.cop_model.index(
            self.panel.cop_model.find_asset_row_by_id(asset.mat_id), 0)
        ok, reason, created = node_actions.import_asset_to_scene(
            self.panel.cop_model, index, context_node=hou.node("/stage"))
        for made in created:
            self.addCleanup(made.destroy)
        self.assertTrue(ok, reason)
        self.assertEqual("Vop", created[0].childTypeCategory().name())
        self.assertIsNotNone(created[0].node("door_to_node/surf"),
                             "the material's interior did not come back")

    def test_a_wrangle_saved_as_code_keeps_the_chosen_language(self):
        wrangle = _wrangle(self)
        before = self.panel.code_model.rowCount()
        held = test_support.asset_ids(self.panel.code_model)
        with _choosing("code", language="Python"):
            self.panel._save_new([wrangle], "code", wrangle)
        self.assertEqual(before + 1, self.panel.code_model.rowCount())
        snippet, = test_support.arrived(self.panel.code_model, held)
        self.assertEqual("Python", snippet.renderer)    # a snippet's language rides the renderer field
        self.assertIn("@Cd = 1;", snippet.code)


class ASaveKeepsTheArtistsSelection(unittest.TestCase):
    """The save stages a COPY, and `hou.copyNodesTo` selects what it makes."""

    def setUp(self):
        if not hou.getenv("OCIO"):
            hou.putenv("OCIO", "/dev/null")
        self.panel = test_support.fixture_panel(self)
        self.panel.prefs.render_on_import = 0

    def test_the_saved_node_is_still_the_selection(self):
        node = _material(self, "door_selected")
        hou.clearAllSelected()
        node.setSelected(True)
        before = self.panel.material_model.rowCount()
        with _choosing("material"):
            self.panel._save_new([node], "material", node)
        self.assertEqual(before + 1, self.panel.material_model.rowCount(),
                         "premise: the material did not save")
        self.assertEqual(
            [node], list(hou.selectedNodes()),
            "after Save to Amaze the saved node is no longer selected")


class ASaveLeavesNothingOnTheUndoStack(unittest.TestCase):
    """The staging copies are the save's own business; the next Ctrl+Z is the artist's."""

    def test_a_material_save_adds_no_undo_entry(self):
        from amaze.render import nodes
        if not hou.getenv("OCIO"):
            hou.putenv("OCIO", "/dev/null")
        prefs = test_support.fixture_prefs(self)
        prefs.render_on_import = 0
        node = _material(self, "door_undo")
        node.setSelected(True, True)
        handler = nodes.NodeHandler(prefs)
        handler._renderer = "Karma"
        hou.undos.clear()
        self.addCleanup(hou.undos.clear)
        self.assertTrue(handler.save_node(node, "doorundo", False),
                        "premise: the material did not save")
        self.assertEqual(
            (), hou.undos.undoLabels(),
            "the save's staging copy left entries on the undo stack, so "
            "the next Ctrl+Z after Save to Amaze undoes the save's noise")

    def test_a_convert_adds_no_undo_entry(self):
        """Convert to rebuilds, converts and saves a twin in scratch: none of it is the artist's."""
        from amaze.actions import materials as material_actions
        from amaze.core import library
        from amaze.render import nodes
        if not hou.getenv("OCIO"):
            hou.putenv("OCIO", "/dev/null")
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        prefs = test_support.fixture_prefs(self)
        prefs.render_on_import = 0
        model = library.MaterialLibrary(preferences=prefs)
        source = nodes.make_karma_builder(hou.node("/mat"), "convert_undo")
        self.addCleanup(source.destroy)
        nodes.wire_builder_output(source, source.createNode("mtlxstandard_surface"))
        held = test_support.asset_ids(model)
        self.assertEqual("Karma", material_actions.add_asset(model, source, "", "", False))
        saved, = test_support.arrived(model, held)
        row = model.find_asset_row_by_id(saved.mat_id)
        hou.undos.clear()
        self.addCleanup(hou.undos.clear)
        with test_support.plugins_loaded("Octane"):    # Karma to Octane runs with no plugin
            ok, report = material_actions.convert(model, model.index(row, 0), "Octane")
        self.assertTrue(ok, "premise: the conversion did not run: %s" % report.summary_lines())
        self.assertEqual((), hou.undos.undoLabels(),
                         "Convert to left its scratch work on the artist's undo stack")


class AnUpdateBeforeARestartSaysSo(unittest.TestCase):
    """The menu reloads from disk and the panel does not, so a new menu can meet an old panel."""

    def test_an_old_panel_gets_the_restart_sentence_and_keeps_the_selection(self):
        import types
        from amaze import messages
        from amaze.utils import rc_calls

        node = _geo(self, "door_unselected")
        hou.clearAllSelected()
        said = []
        fake_ui = types.SimpleNamespace(
            displayMessage=lambda text, *a, **k: said.append(text))
        old_panel = types.SimpleNamespace()    # loaded before the update: no save_from_node
        with mock.patch.object(rc_calls, "_find_panel",
                               return_value=old_panel), \
                mock.patch.object(hou, "ui", fake_ui, create=True):
            rc_calls.save(node)
        self.assertEqual([messages.RESTART_TO_FINISH_UPDATE], said)
        self.assertFalse(node.isSelected(),
                         "a refused save took the user's selection")


class AnUnderscoredCategoryKeepsItsStoredName(unittest.TestCase):
    """`_WIP` reads WIP in every list, and a save files under `_WIP` without minting another."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.categories = self.panel.code_category_model
        self.categories.check_add_category("_WIP")
        self.panel.section_tabs.setChecked("code")
        QtWidgets.QApplication.processEvents()
        self.before = self.categories.rowCount()

    def _save(self, pick=""):
        """A real D09 for a wrangle, choosing the row labelled `pick` when given."""
        seen = {}

        def fake_exec(dialog):
            combo = dialog.combo_cats
            seen["labels"] = [combo.itemText(i) for i in range(combo.count())]
            if pick:
                combo.setCurrentIndex(combo.findText(pick))
            seen["shown"] = combo.currentText()
            dialog._on_accept()
            return 1

        wrangle = _wrangle(self)
        held = test_support.asset_ids(self.panel.code_model)
        with mock.patch.object(save_dialog.SaveDialog, "exec", fake_exec):
            self.panel._save_new([wrangle], "code", wrangle)
        seen["saved"], = test_support.arrived(self.panel.code_model, held)
        return seen

    def _assert_filed_under_the_stored_name(self, asset):
        self.assertEqual(["_WIP"], list(asset.categories),
                         "the asset was filed under a name the sidebar "
                         "does not hold")
        self.assertEqual(self.before, self.categories.rowCount(),
                         "a second category that also reads WIP was made")

    def test_picking_WIP_files_under_WIP(self):
        seen = self._save(pick="WIP")
        self.assertIn("WIP", seen["labels"])
        self.assertNotIn("_WIP", seen["labels"],
                         "the list shows the stored spelling")
        self._assert_filed_under_the_stored_name(seen["saved"])

    def test_standing_on_WIP_pre_selects_it(self):
        self.assertTrue(self.panel._stand_on_category("WIP"),
                        "premise: no row reads WIP")
        seen = self._save()
        self.assertEqual("WIP", seen["shown"],
                         "standing on WIP opened the save on another row")
        self._assert_filed_under_the_stored_name(seen["saved"])

    def test_editing_a_WIP_snippet_leaves_it_there(self):
        code = self.panel.code_model
        row = next(i for i, asset in enumerate(code.assets)
                   if str(asset.code or "").strip())
        self.assertTrue(code.set_tile_category(row, "_WIP"))
        seen = {}

        def accepting(dialog):
            seen["shown"] = dialog._combo_category.currentText()
            dialog._apply()
            return 0

        with mock.patch.object(code_dialog.CodeDialog, "exec", accepting):
            self.panel.sections["code"]._edit_code_row(row)
        self.assertEqual("WIP", seen["shown"],
                         "the editor opened the snippet on another row")
        self._assert_filed_under_the_stored_name(code.assets[row])


if __name__ == "__main__":
    unittest.main()
