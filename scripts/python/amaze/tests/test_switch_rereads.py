"""A library switch drops the keyed-store tables, so the panel never serves rows the disk no longer holds: an open store reads its file ONCE, and without the drop a session that switched away and back would show the first library's old notes, icons and folders until Houdini restarted, hiding edits sync landed behind the cache."""

import json
import os
import shutil
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # BEFORE the app exists ▸p/first-app-picks-the-platform
from PySide6 import QtWidgets  # noqa: E402

import hou  # noqa: E402

from amaze import messages
from amaze.core import database, keyed_store, tile_icons
from amaze.tests import test_support

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _write_settings(panel, **changes):
    path = os.path.join(panel.prefs.path, "settings.json")
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    data.update(changes)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)


class SwitchRereadsCase(unittest.TestCase):
    """One panel for the class - the door under test is the panel's."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def test_switch_rereads_stores_from_disk(self):
        """An edit that lands on disk BEHIND the cache (the other machine, via sync) is visible after the next pass through switch_all_models."""
        panel = self.panel
        prefs = panel.prefs
        self.addCleanup(keyed_store.release)
        name = (tile_icons.icon_names() or ["feather"])[0]
        key = os.path.join(str(prefs.dir), "img", "switch-reread-probe.png")
        self.assertTrue(
            tile_icons.set_override(prefs, key, {"name": name, "bg": "#ef8878"}),
            "the probe write reported failure")
        store = keyed_store.open_store(tile_icons.SPEC, prefs)
        with open(store.path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("#ef8878", text,
                      "the probe never reached the file, so an external "
                      "edit cannot be simulated on it")
        with open(store.path, "w", encoding="utf-8") as handle:
            handle.write(text.replace("#ef8878", "#4af2a1"))
        panel.switch_all_models()
        QtWidgets.QApplication.processEvents()
        self.assertEqual(
            "#4af2a1",
            tile_icons.override_for(prefs, key).get("bg"),
            "the switch served the cached row instead of re-reading the "
            "file - switching back to a library shows stale data until "
            "Houdini restarts")


class TheRegisteredFoldersFollowTheLibrary(unittest.TestCase):
    """Every registered File location vanished from the pane after a library switch: the rows were never lost, the File section simply declared no `library_model_attrs` and nothing repainted. ▸p/folders-follow-the-library"""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def test_the_file_section_declares_its_library_model(self):
        from amaze.panel import sections
        self.assertIn(
            "file_folders_model",
            sections.FileSection.library_model_attrs,
            "the File section's folders are not re-pointed on a library "
            "switch, so the pane keeps showing the previous library's")

    def test_every_declared_model_can_actually_switch(self):
        """Declaring the attribute is only half - `switch_all_models` calls `switch_model_data()` on each, so a model without one turns the switch into an AttributeError."""
        panel = self.panel
        missing = []
        for model in panel.library_models():
            if not hasattr(model, "switch_model_data"):
                missing.append(type(model).__name__)
        self.assertEqual([], missing, "declared but cannot switch: %s"
                         % ", ".join(missing))

    def test_the_folder_model_resets_so_the_view_repaints(self):
        """The folders read THROUGH to prefs, so the rows are right the moment the store is dropped - what was missing is the reset that tells the view."""
        panel = self.panel
        model = panel.file_folders_model
        self.assertIsNotNone(model)
        seen = []
        model.modelReset.connect(lambda: seen.append(True))
        model.switch_model_data()
        QtWidgets.QApplication.processEvents()
        self.assertTrue(
            seen, "switch_model_data emitted no reset, so a view showing "
                  "the old library's folders is never told to redraw")

    def test_a_switch_reaches_the_folder_model(self):
        """End to end through the panel's own door, which is what the library toggle runs."""
        panel = self.panel
        seen = []
        panel.file_folders_model.modelReset.connect(lambda: seen.append(True))
        panel.switch_all_models()
        QtWidgets.QApplication.processEvents()
        self.assertTrue(
            seen, "switch_all_models never reached the File section's "
                  "folders, so the pane keeps the previous library's")


class AfterASwitchFileShowsTheNewLibrarysLocation(unittest.TestCase):
    """A switch while File shows re-picks the location; the grid kept the old one until a click."""

    def test_the_grid_and_the_sidebar_land_on_the_new_library(self):
        panel = test_support.fixture_panel(self)
        panel.section_tabs.setChecked("file")
        QtWidgets.QApplication.processEvents()
        files, folders = panel.file_files_model, panel.file_folders_model
        old = files._folder
        self.assertTrue(old, "premise: File shows the fixture's location")
        theirs = test_support.fresh_files_folder(self)
        settings = os.path.join(panel.prefs.path, "settings.json")
        with open(settings, encoding="utf-8") as handle:
            data = json.load(handle)
        data.update(directory=test_support.fresh_library(self),
                    file_folders=[theirs], last_file_folder=theirs,
                    file_location_records={theirs: {"registered": True}})
        with open(settings, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        panel.switch_all_models()
        QtWidgets.QApplication.processEvents()
        self.assertNotEqual(old, files._folder,
                            "the grid still lists the previous library's location")
        self.assertEqual(theirs, files._folder, "File landed off its remembered location")
        standing = panel.cat_list.selectionModel().selectedIndexes()
        self.assertTrue(standing, "the sidebar stands on no location")
        self.assertEqual(standing[0].data(folders.PathRole) or "", files._folder)


class AfterASwitchAnAssetGridFollowsItsSidebar(unittest.TestCase):
    """A switch reset an asset section's sidebar and left its grid filtered on the old category."""

    def _switch_to_a_fresh_library(self, panel):
        settings = os.path.join(panel.prefs.path, "settings.json")
        with open(settings, encoding="utf-8") as handle:
            data = json.load(handle)
        data.update(directory=test_support.fresh_library(self))
        with open(settings, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        panel.switch_all_models()
        QtWidgets.QApplication.processEvents()

    def test_the_grid_and_the_sidebar_stand_on_one_category(self):
        panel = test_support.fixture_panel(self)
        for key in ("material", "cop", "code", "gradient"):
            with self.subTest(section=key):
                panel.section_tabs.setChecked(key)
                QtWidgets.QApplication.processEvents()
                st = panel._section().stack()
                st.categories.check_add_category("Probe")
                sidebar = panel.cat_list.model()
                sidebar.hide_empty = False
                sidebar.invalidateFilter()
                self.assertTrue(panel._stand_on_category("Probe"), "premise: Probe is a row")
                self.assertEqual("Probe", st.proxy.filter_value(st.model.CategoryRole),
                                 "premise: the grid is filtered on Probe")
                self._switch_to_a_fresh_library(panel)
                self.assertEqual(
                    panel._selected_category_name(),
                    st.proxy.filter_value(st.model.CategoryRole) or "",
                    "the grid keeps the previous library's category")
                self.assertTrue(panel.cat_list.selectionModel().selectedIndexes(),
                                "the sidebar stands on no row")


class AfterASwitchTheGridAndTheSidebarShareOneDocument(unittest.TestCase):
    """Every model re-read its file on a switch, so the grid kept a copy the sidebar never writes."""

    PAIRS = (("material_model", "category_model"),
             ("cop_model", "cop_category_model"),
             ("code_model", "code_category_model"),
             ("gradient_model", "gradient_categories_model"))

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        other = test_support.fresh_library(self)
        settings = os.path.join(self.panel.prefs.path, "settings.json")
        with open(settings, encoding="utf-8") as handle:
            data = json.load(handle)
        data["directory"] = other    # what Preferences saves before it switches
        with open(settings, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        self.panel.switch_all_models()
        QtWidgets.QApplication.processEvents()

    def test_a_sidebar_recolour_reaches_the_grid(self):
        grid = self.panel.material_model
        row = next(index for index, asset in enumerate(grid.assets)
                   if list(asset.categories)[:1] == ["Karma_Mats"])
        self.panel.category_model.set_color("Karma_Mats", "#4af2a1")
        self.assertEqual(
            "#4af2a1", grid.category_color(row),
            "after a switch the grid reads colours from a copy the sidebar "
            "no longer writes")

    def test_each_grid_reads_its_sidebars_document(self):
        apart = [grid for grid, sidebar in self.PAIRS
                 if getattr(self.panel, grid)._data
                 is not getattr(self.panel, sidebar)._data]
        self.assertEqual([], apart,
                         "these grids hold a document their sidebar does not")


class AnUnreadableNodeFileDoesNotStopTheSwitch(unittest.TestCase):
    """A library whose cops.json will not parse: every model still switches, and saving says why not."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.other = test_support.fresh_library(self)
        with open(os.path.join(self.other, "cops.json"), "w",
                  encoding="utf-8") as handle:
            handle.write('{"assets": [')    # cut off mid-sync
        settings = os.path.join(self.panel.prefs.path, "settings.json")
        with open(settings, encoding="utf-8") as handle:
            data = json.load(handle)
        data["directory"] = self.other    # what Preferences saves before it switches
        with open(settings, "w", encoding="utf-8") as handle:
            json.dump(data, handle)

    def test_every_model_reaches_the_new_library(self):
        try:
            self.panel.switch_all_models()
        except (OSError, ValueError) as exc:
            self.fail("the switch stopped at the Node sidebar and left the "
                      "models after it on the previous library: %s" % exc)
        stranded = [name for name in database.DATABASES
                    if not database.DatabaseConnector(name).serves(self.other)]
        self.assertEqual([], stranded,
                         "still serving the previous library: %s" % stranded)
        sidebar = self.panel.cop_category_model
        self.assertEqual(
            ["_All"], [sidebar.data(sidebar.index(row, 0), sidebar.CatSortRole)
                       for row in range(sidebar.rowCount())],
            "the Node sidebar shows categories from a file it could not read")
        self.assertEqual(0, self.panel.cop_model.rowCount())

    def test_a_node_save_is_refused_for_the_file_it_could_not_read(self):
        self.panel.cop_model.switch_model_data()
        with test_support.captured_log() as log:
            self.assertFalse(self.panel.cop_model.save(),
                             "premise: a save over an unread file went ahead")
        self.assertNotIn(
            messages.LIBRARY_NOT_SAVED_ANOTHER_PANEL, log.messages("alert"),
            "the refusal blamed another panel: the failed switch had left "
            "the shared database connection on the previous library")
        self.assertTrue(
            log.matching("could not be read"),
            "the refusal never said the Node file could not be read: %s"
            % log.messages())


class OneLibraryChangeIsOneSwitch(unittest.TestCase):
    """A library chosen with Preferences open is switched to once; closing Preferences adds none."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)

    def _switches_while_open(self, action):
        model = self.panel.material_model
        with mock.patch.object(model, "switch_model_data",
                               wraps=model.switch_model_data) as switch:
            self.panel.show_prefs()
            action(self.panel._prefs_dialog)
            self.panel._prefs_dialog.close()
            QtWidgets.QApplication.processEvents()
        return switch.call_count

    def test_set_library(self):
        other = test_support.fresh_library(self)

        def picked(accept=None):
            self.panel.prefs.dir = other
            _write_settings(self.panel, directory=other)    # the save the fixture panel switches off
            return True

        def set_library(dialog):
            with mock.patch.object(self.panel.prefs, "get_dir_from_user", picked):
                dialog.change_library_path()

        self.assertEqual(1, self._switches_while_open(set_library),
                         "closing Preferences re-read every model a second time")

    def test_test_library(self):
        folder = test_support.scratch_dir("amaze_switch_test_lib_")
        self.addCleanup(shutil.rmtree, folder, True)

        def turn_on(dialog):
            self.panel.prefs.test_dir = folder
            _write_settings(self.panel, test_mode=True, test_dir=folder)    # the save the fixture panel switches off
            dialog.set_test_mode(True)

        self.assertEqual(1, self._switches_while_open(turn_on),
                         "closing Preferences re-read every model a second time")

    def test_a_folder_changed_behind_preferences_is_switched_to_at_close(self):
        other = test_support.fresh_library(self)
        self.assertEqual(
            1, self._switches_while_open(
                lambda dialog: _write_settings(self.panel, directory=other)),
            "closing Preferences left the models on the previous library")

    def test_closing_with_nothing_changed_switches_nothing(self):
        self.assertEqual(0, self._switches_while_open(lambda dialog: None),
                         "closing Preferences switched with no library change")

    def test_a_switch_is_written_to_the_debug_log(self):
        with test_support.captured_log() as log:
            self.panel.switch_all_models()
        self.assertEqual(1, log.messages("session").count("library switched"),
                         "a switch left no line in the debug log to count it by")


class EveryWayOntoALibraryTakesOneOrder(unittest.TestCase):
    """Every way onto a library takes one order: refusal, prepare, models, publish, update, seed."""

    ORDER = ["refusal", "prepare", "models", "publish", "update", "seed"]

    def setUp(self):
        from amaze.actions import library as library_actions
        from amaze.core import texstore
        from amaze.panel import panel as panel_mod
        self.panel = test_support.fixture_panel(self)
        self.order = []
        for owner, name, step in (
                (library_actions, "newer_version", "refusal"),
                (library_actions, "prepare", "prepare"),
                (panel_mod.AmazePanel, "setup", "models"),
                (panel_mod.AmazePanel, "switch_all_models", "models"),
                (texstore, "publish_env", "publish"),
                (library_actions, "update", "update"),
                (library_actions, "seed_starters", "seed")):
            patcher = mock.patch.object(owner, name, self._spy(step, getattr(owner, name)))
            patcher.start()
            self.addCleanup(patcher.stop)

    def _spy(self, step, real):
        def recorded(*args, **kwargs):
            self.order.append(step)
            return real(*args, **kwargs)
        return recorded

    def _assert_order(self, door):
        self.assertEqual(self.ORDER, self.order,
                         "%s opened the library in another order" % door)

    def test_opening_the_pane(self):
        test_support.reopened_panel(self)
        self._assert_order("opening the pane")

    def test_reload_library(self):
        self.panel.open()
        self._assert_order("Reload Library")

    def test_set_library(self):
        other = test_support.fresh_library(self)

        def picked(accept=None):
            self.panel.prefs.dir = other
            _write_settings(self.panel, directory=other)    # the save the fixture panel switches off
            return True

        with mock.patch.object(self.panel.prefs, "get_dir_from_user", picked):
            self.panel.set_library()
        self._assert_order("Set Library")

    def test_closing_preferences(self):
        self.panel.show_prefs()
        _write_settings(self.panel, directory=test_support.fresh_library(self))
        del self.order[:]
        self.panel._prefs_dialog.close()
        QtWidgets.QApplication.processEvents()
        self._assert_order("closing Preferences")

    def test_test_library(self):
        from amaze.dialogs import prefs_dialog
        folder = test_support.scratch_dir("amaze_order_test_lib_")
        self.addCleanup(shutil.rmtree, folder, True)
        self.panel.prefs.test_dir = folder
        dialog = prefs_dialog.PrefsDialog(self.panel.prefs, panel=self.panel)
        self.addCleanup(dialog.deleteLater)
        del self.order[:]
        dialog.set_test_mode(True)
        self._assert_order("Test Library")


class AnUnreadableListIsAskedAboutBeforeTheSwitch(unittest.TestCase):
    """A library whose list will not read asks Repair or Cancel; Cancel keeps the open library."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.broken = test_support.fresh_library(self)
        index = os.path.join(self.broken, "library.json")
        shutil.copyfile(index, index + ".bak-1")    # what Repair puts back
        with open(index, "wb") as handle:
            handle.write(b"{ this is not json")

    def _answering(self, answer, action, picked=None):
        asked = []

        def scripted(message, **kwargs):
            asked.append((str(message), tuple(kwargs.get("buttons", ()))))
            return answer

        ui = mock.MagicMock()
        ui.displayMessage.side_effect = scripted
        ui.selectFile.return_value = picked or self.broken
        with mock.patch.object(hou, "ui", ui, create=True):
            action()
            QtWidgets.QApplication.processEvents()
        return asked

    def test_cancel_keeps_the_open_library_and_writes_nothing(self):
        before = self.panel.prefs.dir
        files = sorted(os.listdir(self.broken))
        asked = self._answering(1, self.panel.set_library)
        self.assertEqual([(messages.LIBRARY_INDEX_UNREADABLE_SWITCHING,
                           messages.BUTTONS_REPAIR_OR_CANCEL)], asked)
        self.assertEqual(before, self.panel.prefs.dir, "Cancel moved the Library Path")
        self.assertEqual(before, self.panel._models_dir, "Cancel left the open library")
        self.assertEqual(files, sorted(os.listdir(self.broken)), "Cancel wrote into the folder")

    def test_a_list_that_has_not_arrived_is_refused_before_anything_is_saved(self):
        held = test_support.fresh_library(self)
        os.remove(os.path.join(held, "library.json"))    # mat/ and img/ stay: it has held a library
        saves = []
        self.panel.prefs.save = lambda *a, **k: saves.append(True)
        before = self.panel.prefs.dir
        asked = self._answering(0, self.panel.set_library, picked=held)
        self.assertEqual([(messages.STARTER_SEED_REFUSED_DIRECTORY_HELD_LIBRARY, ())], asked)
        self.assertEqual([], saves, "the settings were saved, which writes into the picked folder")
        self.assertEqual(before, self.panel.prefs.dir, "the Library Path moved")

    def test_repair_opens_the_picked_library(self):
        self.panel.prefs.save = lambda *a, **k: _write_settings(
            self.panel, directory=self.panel.prefs.real_dir)    # the save the fixture panel switches off
        self._answering(0, self.panel.set_library)
        self.assertEqual(os.path.normpath(self.broken),
                         os.path.normpath(self.panel._models_dir),
                         "Repair did not open the picked library")

    def test_cancel_turns_test_library_back_off(self):
        from amaze.dialogs import prefs_dialog
        from amaze.prefs import prefs as prefs_mod
        folder = test_support.scratch_dir("amaze_broken_test_lib_")
        self.addCleanup(shutil.rmtree, folder, True)
        prefs_mod.seed_test_folder(folder)
        with open(os.path.join(prefs_mod.test_library_dir(folder), "library.json"), "wb") as handle:
            handle.write(b"{ this is not json")
        self.panel.prefs.test_dir = folder
        before = self.panel.prefs.dir
        dialog = prefs_dialog.PrefsDialog(self.panel.prefs, panel=self.panel)
        self.addCleanup(dialog.deleteLater)
        self._answering(1, lambda: dialog._cbx_test_mode.setChecked(True))
        self.assertFalse(self.panel.prefs.test_mode, "Cancel left Test Library on")
        self.assertFalse(dialog._cbx_test_mode.isChecked(), "the switch still shows Test Library on")
        self.assertEqual(before, self.panel.prefs.dir, "Cancel left the open library")


if __name__ == "__main__":
    unittest.main()
