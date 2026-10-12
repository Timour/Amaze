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

from amaze.dialogs import save_dialog  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
