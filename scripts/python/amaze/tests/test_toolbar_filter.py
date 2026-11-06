"""The toolbar's Filter menu, one engine for every section, and what typing in Search costs."""

import contextlib
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
from PySide6 import QtCore, QtGui, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401
from amaze.panel import sections  # noqa: E402
from amaze.tests import test_support  # noqa: E402
from amaze.core import file_library, texture_library  # noqa: E402 - after test_support, which redirects config_root and the cache
from amaze.prefs import prefs as prefs_module  # noqa: E402


class FilterMenuEngineTest(unittest.TestCase):
    """One filter engine for five sections; the panel passes labels and values, never their meaning."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(
            test_support.class_scope(cls))

    def _labels_for(self, key):
        self.panel._on_tab_toggled(key, True)
        self.assertEqual(key, self.panel.current_section,
                         "the tab switch to %r did not take" % key)
        return [act.text() for act in self.panel.menu_filter.actions() if not act.isSeparator()]

    def test_every_section_fills_the_menu_with_its_own_entries(self):
        """Four sections pin their lists exactly; Materials is prefs-gated, so only its first is fixed."""
        expected = {
            "gradient": ["All", "1 color", "2 colors", "3 colors",
                         "4 colors", "5+ colors"],
            "cop": ["All", "SOP", "COP", "LOP", "DOP", "TOP", "CHOP",
                    "Object"],
            "code": ["All", "VEX", "OpenCL", "Python", "Code"],
            "file": ["All", "Images", "Geometry", "Hip"],
        }
        values = {"gradient": ("5+ colors", (5, None)),    # values of two TYPES: the panel interprets neither
                  "code": ("OpenCL", "OpenCL")}
        for key, labels in expected.items():
            self.assertEqual(labels, self._labels_for(key),
                             "the %s section's Filter menu changed" % key)
            if key in values:
                label, value = values[key]
                self.assertEqual(
                    value, self.panel.filter_values[label],
                    "the %s menu no longer carries its value through the "
                    "panel untouched" % key)
        material = self._labels_for("material")
        self.assertEqual("All", material[0],
                         "Materials lost its everything-entry")
        for label in material[1:]:
            self.assertIn(
                label, ["MaterialX", "Redshift", "Octane"],
                "Materials offers something that is not a renderer")

    def test_rebuilds_leave_one_group_holding_only_the_entries_shown(self):
        """The menu is rebuilt on every tab switch, so what fills it must not pile up."""
        for key in ("code", "cop", "gradient", "code", "material", "code"):
            labels = self._labels_for(key)
        QtWidgets.QApplication.sendPostedEvents(
            None, QtCore.QEvent.Type.DeferredDelete)
        groups = self.panel.menu_filter.findChildren(QtGui.QActionGroup)
        self.assertEqual(1, len(groups),
                         "%d action groups alive after six rebuilds" % len(groups))
        self.assertEqual(labels, [act.text() for act in groups[0].actions()],
                         "the group holds actions the menu no longer shows")

    def test_a_pick_narrows_the_grid_and_all_puts_it_back(self):
        """Through the real menu action on countable rows: one language in, everything out."""
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

    def test_all_stores_no_filter_and_the_sidebar_counts_survive_it(self):
        """A renderless row is seen only unfiltered; a label `All` once zeroed every sidebar count."""
        self._labels_for("material")
        self.panel.filter_actions["All"].setChecked(True)
        self.panel.apply_section_filter()
        stored = getattr(self.panel.material_sorted_model, "_filters", {})
        self.assertNotIn(
            self.panel.material_model.RendererRole, stored,
            "All still stores a filter - every row pays an "
            "index.data() on every pass to reach the same yes")
        if not self.panel.material_model.rowCount():
            self.skipTest("fixture library has no materials")
        self.assertTrue(
            self.panel.category_model.showing_all_renderers(),
            "All does not read as all to the category model, so the "
            "sidebar hides categories the grid is showing")
        self.assertEqual(
            self.panel.category_model.rowCount(),
            self.panel.category_sorted_model.rowCount(),
            "the sidebar is hiding categories while the grid shows "
            "every material")

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

    def test_the_material_menu_has_icons_and_sets_all_apart(self):
        """Every Material entry carries its icon and a separator follows All; Code keeps plain text."""
        self._labels_for("material")
        actions = self.panel.menu_filter.actions()
        self.assertTrue(actions[1].isSeparator(), "no separator under All")
        entries = [act for act in actions if not act.isSeparator()]
        self.assertTrue(all(not act.icon().isNull() for act in entries),
                        "a Material entry has no icon")
        self._labels_for("code")
        actions = self.panel.menu_filter.actions()
        self.assertFalse(any(act.isSeparator() for act in actions), "Code grew a separator")
        self.assertTrue(all(act.icon().isNull() for act in actions), "Code grew icons")

    def test_the_choice_is_saved_by_id_so_its_label_can_change(self):
        """The MaterialX entry saves its id `Karma`, and a saved `Karma` checks it again."""
        self._labels_for("material")
        if "Karma" not in self.panel.filter_actions:
            self.skipTest("Karma not enabled in this fixture")

        def back_to_all():
            self._labels_for("material")
            every = self.panel.filter_actions["All"]
            every.setChecked(True)
            self.panel.filter_menu_changed(every)
        self.addCleanup(back_to_all)
        act = self.panel.filter_actions["Karma"]
        self.assertEqual("MaterialX", act.text(), "the Karma entry is not shown as MaterialX")
        act.setChecked(True)
        self.panel.filter_menu_changed(act)
        self.assertEqual("Karma", self.panel.prefs.section_filter("material"),
                         "the saved choice is the label, so renaming it loses the choice")
        self._labels_for("code")
        self._labels_for("material")
        checked = self.panel.filter_action_group.checkedAction()
        self.assertEqual("MaterialX", checked.text() if checked is not None else "",
                         "a saved Karma did not bring the MaterialX entry back")

    def test_a_choice_no_longer_offered_falls_back_to_all(self):
        """A renderer switched off in Preferences takes its entry, leaving nothing checked on nothing."""
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
        """Colors filters on a range: `5+ colors` keeps a 9-color palette while `4 colors` does not."""
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
        """File rows mix several kinds and the filter picks one, on a real FileFiles over a real folder."""
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
        prefs = prefs_module.Prefs()  # the real Prefs, as file_folders is read-only
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
            kind = {entry.label: entry.value
                    for entry in sections.FileSection.FILTER_CHOICES}[label]
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


class RememberedFilterSettingsTest(unittest.TestCase):
    """The settings file is a contract with data on disk: one filter key per section."""

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

    def test_an_old_settings_file_keeps_its_renderer_unless_the_new_key_is_there(self):
        """Both keys present means the file was written since the upgrade - the new one is the truth."""
        p = self._prefs({"last_renderer": "Redshift"})
        self.assertEqual(
            "Redshift", p.section_filter("material"),
            "the remembered renderer was dropped on upgrade")
        p = self._prefs({"last_renderer": "Redshift",
                         "section_filters": {"material": "Karma",
                                             "code": "VEX"}})
        self.assertEqual("Karma", p.section_filter("material"),
                         "the retired key overrode the live one")
        self.assertEqual("VEX", p.section_filter("code"))

    def test_what_is_set_is_what_is_saved(self):
        p = self._prefs({})
        self.assertEqual("", p.section_filter("gradient"),
                         "an unvisited section claims a filter it was "
                         "never given")
        p.set_section_filter("cop", "LOP")
        p.save()
        again = prefs_module.Prefs()
        again.path = p.path
        again.load()
        self.assertEqual(
            "LOP", again.section_filter("cop"),
            "the choice did not survive the round trip to disk")


class TypingCostsOnePassNotOnePerKeystroke(unittest.TestCase):
    """Debounced box, batched filter pair, counted by `invalidateFilter`. ▸p/filter-pass-cost"""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(
            test_support.class_scope(cls))
        cls.panel._on_tab_toggled("material", True)

    def setUp(self):
        self.panel._filter_timer.stop()
        self.panel.line_filter.clear()
        self.panel.filter_thumb_view()
        _app.processEvents()

    def _type(self, word):
        """A keystroke: the text lands and `textEdited` carries it; Qt emits it only for typed changes."""
        box = self.panel.line_filter
        for length in range(1, len(word) + 1):
            box.setText(word[:length])
            box.textEdited.emit(word[:length])

    def _settle(self):
        """Run the pending debounce NOW, the way the pause after typing does."""
        timer = self.panel._filter_timer
        self.assertTrue(timer.isActive(),
                        "typing left no pending filter, so nothing "
                        "would ever narrow the grid")
        timer.stop()
        self.panel.filter_thumb_view()
        _app.processEvents()

    @staticmethod
    @contextlib.contextmanager
    def _passes():
        """Count the `invalidateFilter` passes a block runs, on the class, where the time goes."""
        from amaze.core import grid_proxy
        real = grid_proxy.GridProxyModel.invalidateFilter
        seen = []

        def counting(proxy, *args, **kwargs):
            seen.append(proxy)
            return real(proxy, *args, **kwargs)

        grid_proxy.GridProxyModel.invalidateFilter = counting
        try:
            yield seen
        finally:
            grid_proxy.GridProxyModel.invalidateFilter = real

    def test_a_typed_word_costs_ONE_pass_and_it_comes_after_the_typing(self):
        """Five keystrokes queue one pass; the pause runs it."""
        with self._passes() as seen:
            self._type("metal")
            _app.processEvents()
            while_typing = len(seen)
            self._settle()
            settled = len(seen)
        self.assertEqual(
            0, while_typing,
            "typing filtered %d time(s) mid-word, so the debounce on "
            "line_filter.textEdited is gone" % while_typing)
        self.assertEqual(
            1, settled,
            "the settled word cost %d passes, not one" % settled)

    def test_swapping_a_name_search_for_a_tag_search_costs_ONE_pass(self):
        """A `:` drops the name filter and sets the tag filter, two refilters `one_pass` makes one."""
        self._type("metal")
        self._settle()
        with self._passes() as seen:
            self._type(":wood")
            self._settle()
            swapped = len(seen)
        self.assertEqual(
            1, swapped,
            "the swap cost %d passes, not one - the remove/set pair is "
            "running outside `one_pass`" % swapped)

    def test_a_section_switch_with_every_filter_set_costs_ONE_pass(self):
        """Category, search, renderer and favourites all standing: coming back is one pass."""
        panel = self.panel
        panel._on_tab_toggled("material", True)
        panel._stand_on_category("usds")
        panel.line_filter.setText("a")
        panel.filter_thumb_view()
        renderers = [label for label in panel.filter_actions if label != "All"]
        self.assertTrue(renderers, "premise: no renderer filter to set")
        panel.filter_actions[renderers[0]].trigger()
        panel.cb_favsonly.setChecked(True)
        self.addCleanup(panel.cb_favsonly.setChecked, False)
        self.addCleanup(lambda: panel.filter_actions["All"].trigger())
        self.addCleanup(panel._stand_on_all_category)
        proxy = panel.material_sorted_model
        self.assertEqual(4, len(proxy._filters), "premise: a filter is not set")
        panel._on_tab_toggled("code", True)
        with self._passes() as seen:
            panel._on_tab_toggled("material", True)
        mine = [p for p in seen if p is proxy]
        self.assertEqual(1, len(mine),
                         "coming back to Material cost %d passes" % len(mine))
        self.assertEqual("usds", proxy.filter_value(
            panel.material_model.CategoryRole),
            "the switch did not put the category back")

    def test_the_settled_text_is_what_the_grid_filters_on(self):
        """A debounce that dropped the last keystroke would cost more than the passes it saves."""
        self._type("metal")
        self._settle()
        stored = getattr(    # the proxy's own store, as MultiFilterProxyModel has no reader
            self.panel.material_sorted_model, "_filters", {})
        self.assertEqual(
            "metal", stored.get(QtCore.Qt.ItemDataRole.DisplayRole),
            "the grid is filtering on something other than the word "
            "that was typed")


if __name__ == "__main__":
    unittest.main()


