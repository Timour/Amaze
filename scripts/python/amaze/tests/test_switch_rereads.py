"""A library switch drops the keyed-store tables, so the panel never serves rows the disk no longer holds: an open store reads its file ONCE, and without the drop a session that switched away and back would show the first library's old notes, icons and folders until Houdini restarted, hiding edits sync landed behind the cache."""

import json
import os
import unittest

from PySide6 import QtWidgets

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


if __name__ == "__main__":
    unittest.main()
