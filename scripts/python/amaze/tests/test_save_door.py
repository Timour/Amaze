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

    def test_a_material_offers_material_and_node(self):
        keys = self.panel._save_targets([_material(self)])
        self.assertIn("material", keys)
        self.assertIn("cop", keys, "a material can no longer go to Node")
        self.assertNotIn("code", keys)

    def test_a_wrangle_offers_code_and_node_but_not_material(self):
        keys = self.panel._save_targets([_wrangle(self)])
        self.assertEqual({"code", "cop"}, set(keys) & {"code", "cop"})
        self.assertNotIn("material", keys)

    def test_a_ramp_node_offers_color(self):
        self.assertIn("gradient", self.panel._save_targets([_ramp_node(self)]))

    def test_a_multi_selection_never_offers_one_node_sections(self):
        nodes = [_material(self, "m1"), _material(self, "m2")]
        keys = self.panel._save_targets(nodes)
        self.assertIn("material", keys)
        self.assertNotIn("gradient", keys)
        self.assertNotIn("code", keys)


class TheDoorOpensOnTheLikeliestSection(unittest.TestCase):

    def test_a_material_in_a_material_network_opens_on_material(self):
        node = _material(self)
        self.assertEqual("material",
                         sections.save_guess(["material", "cop"], [node]))

    def test_a_subnet_outside_a_material_network_opens_on_node(self):
        sub = hou.node("/obj").createNode("subnet", "door_obj_subnet")
        self.addCleanup(sub.destroy)
        self.assertEqual("cop",
                         sections.save_guess(["material", "cop"], [sub]))

    def test_a_wrangle_opens_on_code(self):
        self.assertEqual(
            "code", sections.save_guess(["code", "cop"], [_wrangle(self)]))

    def test_the_open_section_wins_when_it_can_take_the_node(self):
        self.assertEqual("cop", sections.save_guess(
            ["code", "cop"], [_wrangle(self)], prefer="cop"))

    def test_a_section_that_cannot_take_it_is_not_preferred(self):
        self.assertEqual("code", sections.save_guess(
            ["code", "cop"], [_wrangle(self)], prefer="file"))


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

    def test_changing_section_swaps_the_categories(self):
        dialog = self._dialog()
        dialog.combo_section.setCurrentIndex(1)
        self.assertEqual(["Toolbox"], self._cats(dialog))
        self.assertEqual("code", dialog.section)

    def test_language_is_live_only_for_code(self):
        dialog = self._dialog()
        self.assertFalse(dialog.combo_language.isEnabled())
        dialog.combo_section.setCurrentIndex(1)
        self.assertTrue(dialog.combo_language.isEnabled())
        self.assertEqual("OpenCL", dialog.combo_language.currentText())

    def test_a_greyed_language_is_nobodys_answer(self):
        dialog = self._dialog()
        dialog._on_accept()
        self.assertEqual("", dialog.language)

    def test_the_typed_name_survives_a_section_change(self):
        dialog = self._dialog()
        dialog.line_name.setText("typed")
        dialog.combo_section.setCurrentIndex(1)
        dialog._on_accept()
        self.assertEqual("typed", dialog.name)


class TheChosenSectionIsWhereTheSaveLands(unittest.TestCase):

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.panel.prefs.render_on_import = 0

    def test_a_material_saved_to_node_comes_back_in_a_material_library(self):
        node = _material(self, "door_to_node")
        before = self.panel.cop_model.rowCount()
        with _choosing("cop"):
            self.panel._save_new([node], "material", node)
        self.assertEqual(before + 1, self.panel.cop_model.rowCount(),
                         "the save did not land in Node")
        asset = self.panel.cop_model._assets[-1]
        self.assertEqual("VOP", asset.renderer)
        index = self.panel.cop_model.index(before, 0)
        ok, reason, created = self.panel.cop_model.import_asset_to_scene(
            index, context_node=hou.node("/stage"))
        for made in created:
            self.addCleanup(made.destroy)
        self.assertTrue(ok, reason)
        self.assertEqual("Vop", created[0].childTypeCategory().name())
        self.assertIsNotNone(created[0].node("door_to_node/surf"),
                             "the material's interior did not come back")

    def test_a_wrangle_saved_as_code_keeps_the_chosen_language(self):
        wrangle = _wrangle(self)
        before = self.panel.code_model.rowCount()
        with _choosing("code", language="Python"):
            self.panel._save_new([wrangle], "code", wrangle)
        self.assertEqual(before + 1, self.panel.code_model.rowCount())
        snippet = self.panel.code_model._assets[-1]
        self.assertEqual("Python", snippet.renderer)    # a snippet's language rides the renderer field
        self.assertIn("@Cd = 1;", snippet.code)

    def test_an_empty_wrangle_does_not_offer_code(self):
        wrangle = _wrangle(self)
        wrangle.parm("snippet").set("   ")
        self.assertNotIn("code", self.panel._save_targets([wrangle]))


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
        with mock.patch.object(save_dialog.SaveDialog, "exec", fake_exec):
            self.panel._save_new([wrangle], "code", wrangle)
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
        self._assert_filed_under_the_stored_name(
            self.panel.code_model.assets[-1])

    def test_standing_on_WIP_pre_selects_it(self):
        self.assertTrue(self.panel._stand_on_category("WIP"),
                        "premise: no row reads WIP")
        seen = self._save()
        self.assertEqual("WIP", seen["shown"],
                         "standing on WIP opened the save on another row")
        self._assert_filed_under_the_stored_name(
            self.panel.code_model.assets[-1])

    def test_editing_a_WIP_snippet_leaves_it_there(self):
        code = self.panel.code_model
        row = next(i for i, asset in enumerate(code.assets)
                   if str(asset.code or "").strip())
        self.assertTrue(code.set_tile_category(row, "_WIP"))
        seen = {}

        def accepting(dialog):
            seen["shown"] = dialog._combo_category.currentText()
            dialog._on_accept()
            return 1

        with mock.patch.object(code_dialog.CodeDialog, "exec", accepting):
            self.panel.sections["code"]._edit_code_row(row)
        self.assertEqual("WIP", seen["shown"],
                         "the editor opened the snippet on another row")
        self._assert_filed_under_the_stored_name(code.assets[row])


if __name__ == "__main__":
    unittest.main()
