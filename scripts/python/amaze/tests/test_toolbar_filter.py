"""The Search box: one label, an empty field, in every tab - the label reads Search, the box shows NO placeholder anywhere, and the box's tooltip is where :tag gets taught. These tests drive the real tab switch, so a section that starts writing its own text again turns them red."""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # BEFORE the app exists ▸p/first-app-picks-the-platform
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401
from amaze.panel import sections  # noqa: E402
from amaze.tests import test_support  # noqa: E402
from amaze.core import file_library, texture_library  # noqa: E402 - AFTER test_support, which redirects config_root and the cache; a module resolving a path at import time would reach the user's own files
from amaze.prefs import prefs as prefs_module  # noqa: E402


class SearchBoxTest(unittest.TestCase):
    """Driven on a constructed panel, tab by tab."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(
            test_support.class_scope(cls))

    def _placeholder_for(self, key):
        self.panel._on_tab_toggled(key, True)
        self.assertEqual(key, self.panel.current_section,
                         "the tab switch to %r did not take" % key)
        return self.panel.line_filter.placeholderText()

    def test_the_label_reads_search(self):
        """The box searches, so the label says Search - Filter was the old word."""
        self.assertEqual(
            "Search", self.panel.filter_label.text(),
            "the toolbar label next to the box changed")

    def test_the_box_stays_empty_in_every_section(self):
        """No placeholder text in any tab - the empty box IS the design."""
        for key, label in sections.all_sections():
            self.assertEqual(
                "", self._placeholder_for(key),
                "the %s section writes a placeholder into the "
                "Search box again" % label)

    def test_the_online_browser_stays_empty_too(self):
        """Online mode is a VIEW MODE over Materials with its own placeholder history - it follows the same rule."""
        self._placeholder_for("material")
        self.panel.open_online_source("PhysicallyBased")
        try:
            self.assertTrue(self.panel._is_online(),
                            "the panel did not enter online mode, so "
                            "this test is not exercising it")
            online = self.panel.line_filter.placeholderText()
        finally:
            self.panel.leave_online_world()  # the real leave path - exit_online_materials is the mode exit alone and would leave the grid online
        self.assertEqual(
            "", online,
            "the online browser writes a placeholder into the "
            "Search box again (%r)" % online)


class FilterMenuEngineTest(unittest.TestCase):
    """One menu, one button, five sections - ONE engine: the panel carries a label to a section and a value back, and never learns what a value means."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(
            test_support.class_scope(cls))

    def _labels_for(self, key):
        self.panel._on_tab_toggled(key, True)
        self.assertEqual(key, self.panel.current_section,
                         "the tab switch to %r did not take" % key)
        return [act.text() for act in self.panel.menu_filter.actions()]

    def test_every_section_fills_the_menu_with_its_own_entries(self):
        """The design, tab by tab: four sections pin their lists exactly; Materials is prefs-gated so only its everything-entry is fixed."""
        expected = {
            "gradient": ["All", "1 color", "2 colors", "3 colors",
                         "4 colors", "5+ colors"],
            "cop": ["All", "SOP", "COP", "LOP", "DOP", "TOP", "CHOP",
                    "Object"],
            "code": ["All", "VEX", "OpenCL", "Python", "Code"],
            "file": ["All", "Images", "Geometry", "Hip"],
        }
        for key, labels in expected.items():
            self.assertEqual(labels, self._labels_for(key),
                             "the %s section's Filter menu changed" % key)
        material = self._labels_for("material")
        self.assertEqual("All", material[0],
                         "Materials lost its everything-entry")
        for label in material[1:]:
            self.assertIn(
                label, ["Karma", "Redshift", "Octane"],
                "Materials offers something that is not a renderer")

    def test_the_panel_never_interprets_a_value(self):
        """The engine's whole claim: two sections filter on values of different TYPES (a renderer string, a (low, high) palette-size pair), so a panel that understood either one could not serve both."""
        self._labels_for("gradient")
        self.assertEqual(
            (5, None), self.panel.filter_values["5+ colors"],
            "the Colors menu no longer carries its range through the "
            "panel untouched")
        self._labels_for("code")
        self.assertEqual(
            "OpenCL", self.panel.filter_values["OpenCL"],
            "the Code menu's value changed shape")

    def test_a_pick_narrows_the_grid_and_all_puts_it_back(self):
        """Driven through the real menu action, in the section whose rows the fixture can count: one language in, everything out."""
        self._labels_for("code")
        model = self.panel.code_model
        total = model.rowCount()
        if not total:
            self.skipTest("fixture library has no code snippets")
        languages = {
            (model.index(row, 0).data(model.RendererRole) or "")
            for row in range(total)
        }
        pick = next((lang for lang in languages
                     if lang in self.panel.filter_actions), "")
        if not pick:
            self.skipTest("no snippet carries a language the menu offers")
        expected = sum(
            1 for row in range(total)
            if pick.lower() in (
                model.index(row, 0).data(model.RendererRole) or "").lower()
        )
        self.panel.filter_actions[pick].setChecked(True)
        self.panel.filter_menu_changed(self.panel.filter_actions[pick])
        self.assertEqual(
            expected, self.panel.code_sorted_model.rowCount(),
            "picking %r did not narrow the Code grid to the snippets "
            "written in it" % pick)
        self.panel.filter_actions["All"].setChecked(True)
        self.panel.filter_menu_changed(self.panel.filter_actions["All"])
        self.assertEqual(
            total, self.panel.code_sorted_model.rowCount(),
            "All does not put every snippet back")

    def test_all_stores_no_filter_at_all(self):
        """All REMOVES the filter rather than storing an accept-everything value - a material with no renderer (Repair mints those) has no other way to be seen."""
        self._labels_for("material")
        self.panel.filter_actions["All"].setChecked(True)
        self.panel.apply_section_filter()
        stored = getattr(self.panel.material_sorted_model, "_filters", {})
        self.assertNotIn(
            self.panel.material_model.RendererRole, stored,
            "All still stores a filter - every row pays an "
            "index.data() on every pass to reach the same yes")

    def test_each_section_remembers_its_own_choice(self):
        """One shared key would mean picking Redshift in Materials and finding Nodes narrowed to nothing."""
        self._labels_for("code")
        act = self.panel.filter_actions["Python"]
        act.setChecked(True)
        self.panel.filter_menu_changed(act)
        self._labels_for("cop")
        checked = self.panel.filter_action_group.checkedAction()
        self.assertEqual(
            "All", checked.text() if checked is not None else "",
            "the Code section's choice followed the user into Nodes")
        self._labels_for("code")
        checked = self.panel.filter_action_group.checkedAction()
        self.assertEqual(
            "Python", checked.text() if checked is not None else "",
            "Code did not come back to the language it was left on")
        self.panel.filter_actions["All"].setChecked(True)
        self.panel.filter_menu_changed(self.panel.filter_actions["All"])

    def test_a_choice_no_longer_offered_falls_back_to_all(self):
        """A renderer switched off in Preferences takes its entry with it - the menu must not be left checked on nothing."""
        self._labels_for("material")
        if "Redshift" not in self.panel.filter_actions:
            self.skipTest("Redshift not enabled in this fixture")
        act = self.panel.filter_actions["Redshift"]
        act.setChecked(True)
        self.panel.filter_menu_changed(act)
        before = self.panel.prefs.renderer_redshift_enabled
        self.panel.prefs.renderer_redshift_enabled = False
        self.addCleanup(setattr, self.panel.prefs,
                        "renderer_redshift_enabled", before)
        self.panel.update_renderer_toggles()
        self.assertNotIn("Redshift", self.panel.filter_actions,
                         "a disabled renderer is still offered")
        checked = self.panel.filter_action_group.checkedAction()
        self.assertEqual(
            "All", checked.text() if checked is not None else "",
            "the menu is checked on an entry that no longer exists")
        self.assertNotIn(
            self.panel.material_model.RendererRole,
            getattr(self.panel.material_sorted_model, "_filters", {}),
            "the grid is still filtered to a renderer the menu no "
            "longer offers")

    def test_the_palette_sizes_actually_filter(self):
        """Colors filters on a range, so the last entry is open: `5+ colors` has to keep a 9-color palette while `4 colors` does not."""
        self._labels_for("gradient")
        model = self.panel.gradient_model
        proxy = self.panel.gradient_sorted_model
        total = model.rowCount()
        if not total:
            self.skipTest("fixture library has no palettes")
        held = [len((model.entry(row) or {}).get("colors") or ())
                for row in range(total)]
        for label in ("3 colors", "5+ colors"):
            act = self.panel.filter_actions[label]
            act.setChecked(True)
            self.panel.filter_menu_changed(act)
            fewest, most = self.panel.filter_values[label]
            expected = sum(
                1 for count in held
                if count >= fewest and (most is None or count <= most))
            self.assertEqual(
                expected, proxy.rowCount(),
                "%r shows %d palettes, not the %d holding that many "
                "colors (sizes in the fixture: %r)"
                % (label, proxy.rowCount(), expected, sorted(set(held))))
        self.panel.filter_actions["All"].setChecked(True)
        self.panel.filter_menu_changed(self.panel.filter_actions["All"])
        self.assertEqual(total, proxy.rowCount(),
                         "All does not put every palette back")

    def test_the_file_kinds_actually_filter(self):
        """The File section's rows are one list of several KINDS, so its filter is the way back to one of them - driven on a real FileFiles over a real folder (the fixture panel has no folders registered); the proxy and the model are the shipped ones either way."""
        folder = tempfile.mkdtemp(prefix="amaze_filter_kinds_")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        for name in ("a.png", "b.png", "c.obj", "d.hip", "e.txt"):
            with open(os.path.join(folder, name), "w") as handle:
                handle.write("x")
        home = tempfile.mkdtemp(prefix="amaze_filter_prefs_")
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        with open(os.path.join(home, "settings.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"file_folders": [folder]}, handle)
        prefs = prefs_module.Prefs()  # the real Prefs: file_folders is read-only, and a stub would be a second copy of what FileFiles reads
        prefs.path = home
        prefs.load()
        model = file_library.FileFiles(prefs)
        model.set_folder(folder)
        proxy = texture_library.TextureFilterProxyModel()
        proxy.setSourceModel(model)
        everything = proxy.rowCount()
        self.assertEqual(5, everything,
                         "the fixture folder did not load as five rows")
        for label, expected in (("Images", 2), ("Geometry", 1), ("Hip", 1)):
            kind = dict(sections.FileSection.FILTER_CHOICES)[label]
            proxy.set_kind_filter(kind)
            self.assertEqual(
                expected, proxy.rowCount(),
                "%r shows %d rows, not the %d files of that kind"
                % (label, proxy.rowCount(), expected))
        proxy.set_kind_filter(None)
        self.assertEqual(
            everything, proxy.rowCount(),
            "All does not put every file back - including the .txt, "
            "which has no kind of its own to be found under")

    def test_the_sidebar_counts_survive_all(self):
        """The panel once handed the category model the LABEL `All`, which Categories lowercases and substring-matches - no renderer matched, every count read 0, and Hide Empty Categories emptied the sidebar."""
        self._labels_for("material")
        if not self.panel.material_model.rowCount():
            self.skipTest("fixture library has no materials")
        self.panel.filter_actions["All"].setChecked(True)
        self.panel.apply_section_filter()
        self.assertTrue(
            self.panel.category_model.showing_all_renderers(),
            "All does not read as all to the category model, so the "
            "sidebar hides categories the grid is showing")
        self.assertEqual(
            self.panel.category_model.rowCount(),
            self.panel.category_sorted_model.rowCount(),
            "the sidebar is hiding categories while the grid shows "
            "every material")


class RememberedFilterSettingsTest(unittest.TestCase):
    """The settings file, a contract with data already on disk: one key per section, where there was one renderer for Materials alone."""

    def _prefs(self, settings):
        home = tempfile.mkdtemp(prefix="amaze_filter_settings_")
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        with open(os.path.join(home, "settings.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(settings, handle)
        p = prefs_module.Prefs()
        p.path = home
        p.load()
        return p

    def test_an_old_settings_file_keeps_its_renderer(self):
        """An upgrade must open on the renderer the user left it on, not silently back at All."""
        p = self._prefs({"last_renderer": "Redshift"})
        self.assertEqual(
            "Redshift", p.section_filter("material"),
            "the remembered renderer was dropped on upgrade")

    def test_the_old_key_does_not_override_the_new_one(self):
        """Both keys present means the file was written since the upgrade - the new one is the truth."""
        p = self._prefs({"last_renderer": "Redshift",
                         "section_filters": {"material": "Karma",
                                             "code": "VEX"}})
        self.assertEqual("Karma", p.section_filter("material"),
                         "the retired key overrode the live one")
        self.assertEqual("VEX", p.section_filter("code"))

    def test_a_section_with_no_memory_answers_empty(self):
        p = self._prefs({})
        self.assertEqual("", p.section_filter("gradient"),
                         "an unvisited section claims a filter it was "
                         "never given")

    def test_what_is_set_is_what_is_saved(self):
        p = self._prefs({})
        p.set_section_filter("cop", "LOP")
        p.save()
        again = prefs_module.Prefs()
        again.path = p.path
        again.load()
        self.assertEqual(
            "LOP", again.section_filter("cop"),
            "the choice did not survive the round trip to disk")


if __name__ == "__main__":
    unittest.main()


