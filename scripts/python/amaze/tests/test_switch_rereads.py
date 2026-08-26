"""A library switch drops the keyed-store tables, so the panel never serves rows the disk no longer holds: an open store reads its file ONCE, and without the drop a session that switched away and back would show the first library's old notes, icons and folders until Houdini restarted, hiding edits sync landed behind the cache."""

import json
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # BEFORE the app exists ▸p/first-app-picks-the-platform
from PySide6 import QtWidgets  # noqa: E402

from amaze.core import keyed_store, tile_icons
from amaze.tests import test_support

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


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


if __name__ == "__main__":
    unittest.main()
