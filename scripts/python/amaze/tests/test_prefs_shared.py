"""Shared settings are stored in the library: setting `dir` loads them."""

import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import library_db, model_registry, section_list  # noqa: E402
from amaze.dialogs import prefs_window  # noqa: E402

STORE = "DataBase.json"    # the library's own database: its `settings` section is the store
from amaze.prefs import prefs as prefs_mod   # noqa: E402
from amaze.tests import test_support         # noqa: E402


class SharedPrefsCase(unittest.TestCase):
    """Two settings folders and one library, like the real pair of Macs."""

    def setUp(self):
        self.home_a = tempfile.mkdtemp(prefix="amaze_shared_a_")
        self.home_b = tempfile.mkdtemp(prefix="amaze_shared_b_")
        self.lib = tempfile.mkdtemp(prefix="amaze_shared_lib_")
        for folder in (self.home_a, self.home_b, self.lib):
            self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        with open(os.path.join(self.lib, STORE), "w", encoding="utf-8") as handle:
            json.dump({"format": 5}, handle)    # a library: settings go only where one already is
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)

    def machine(self, home):
        """A Prefs the way a session builds one - load settings, then set the library."""
        p = prefs_mod.Prefs()
        p.path = home
        p.load()
        p.library_user = "u-" + os.path.basename(home)    # every change records its user
        p.dir = self.lib + "/"
        return p

    def settings_doc(self, home):
        with open(os.path.join(home, "settings.json"),
                  encoding="utf-8") as handle:
            return json.load(handle)

    def store_doc(self):
        library_db.flush()
        with open(os.path.join(self.lib, STORE), encoding="utf-8") as handle:
            return {"prefs": json.load(handle).get("settings", {})}


class AChangeIsReadOnTheNextMachine(SharedPrefsCase):
    """Shared means the OTHER machine's session reads your value, from the library alone."""

    def test_a_saved_change_is_the_next_machines_value(self):
        a = self.machine(self.home_a)
        a.rendersize = 512
        # OFF, never ON - asserting True passes on the default alone.
        a.renderer_octane_enabled = False
        a.render_on_import = 0    # falsy: stored in a record, so it is not read as a delete
        a.save()
        test_support.reset_database_singletons()
        b = self.machine(self.home_b)
        self.assertEqual(512, b.rendersize,
                         "machine B still returns its own default - "
                         "the store was not loaded")
        self.assertFalse(b.renderer_octane_enabled,
                         "a renderer flag did not reach machine B")
        self.assertEqual(0, b.render_on_import,
                         "a falsy shared value did not survive")


class TheSharedKeysAreWrittenAsTheCopyAlone(SharedPrefsCase):
    """`settings.json` holds bootstrap and the copy of the shared keys, never them at top level."""

    def test_settings_json_holds_the_copy_not_the_flat_keys(self):
        a = self.machine(self.home_a)
        a.rendersize = 512
        a.save()
        doc = self.settings_doc(self.home_a)
        self.assertNotIn(
            "rendersize", doc,
            "the top-level key is still written - two places for one "
            "value is the mismatch this test exists to prevent")
        self.assertEqual(
            512, doc.get("shared_settings", {}).get("rendersize"),
            "the last-known copy is missing, so an unreachable "
            "library would reset every shared setting")
        self.assertIn("directory", doc,
                      "bootstrap must stay top-level - it is how the "
                      "library is found at all")



class TheCopyIsUsedForAnUnreachableLibrary(SharedPrefsCase):
    """The library is the source; the copy opens the panel when the share is down and must remain."""

    def test_values_are_kept_when_the_library_is_gone(self):
        a = self.machine(self.home_a)
        a.rendersize = 512
        a.save()
        shutil.rmtree(self.lib)
        test_support.reset_database_singletons()
        p = prefs_mod.Prefs()
        p.path = self.home_a
        p.load()
        self.assertEqual(512, p.rendersize,
                         "the copy was not used with the library "
                         "unreachable")
        p.save()          # must not raise, and must not lose the copy
        doc = self.settings_doc(self.home_a)
        self.assertEqual(
            512, doc.get("shared_settings", {}).get("rendersize"),
            "a save without the library emptied the copy")

    def test_a_latched_store_leaves_attributes_and_copy_alone(self):
        a = self.machine(self.home_a)
        a.rendersize = 512
        a.save()
        library_db.flush()
        store_path = os.path.join(self.lib, STORE)
        with open(store_path, "w", encoding="utf-8") as handle:
            handle.write('{"settings": {"rendersize"')      # truncated
        with open(store_path, "rb") as handle:
            broken = handle.read()
        test_support.reset_database_singletons()
        p = prefs_mod.Prefs()
        p.path = self.home_a
        p.load()
        self.assertEqual(512, p.rendersize,
                         "a latched store did not fall back to the "
                         "copy")
        p.rendersamples = 32
        p.save()
        with open(store_path, "rb") as handle:
            self.assertEqual(broken, handle.read(),
                             "a save wrote over a damaged store - "
                             "it stays read-only so the damaged file is kept")
        doc = self.settings_doc(self.home_a)
        self.assertEqual(
            32, doc.get("shared_settings", {}).get("rendersamples"),
            "the session's change was not kept locally while the "
            "store was read-only")


class TheLibraryIsReadWhenDirIsSet(SharedPrefsCase):
    """Setting `dir` after load must read the store, or the first save puts local defaults over it."""

    def test_pointing_dir_at_a_library_reads_it_without_a_load(self):
        a = self.machine(self.home_a)
        a.rendersize = 512
        a.save()
        test_support.reset_database_singletons()
        fresh = prefs_mod.Prefs()
        fresh.path = self.home_b       # no settings.json, no load()
        fresh.dir = self.lib + "/"
        self.assertEqual(512, fresh.rendersize,
                         "setting `dir` did not load the store - a "
                         "fresh install would overwrite the library's "
                         "settings on its first save")

    def test_an_invalid_value_in_the_store_is_validated_like_a_load(self):
        """A hand edit can put text where a size goes, so setting `dir` validates as load does."""
        with open(os.path.join(self.lib, STORE), "w",
                  encoding="utf-8") as handle:
            json.dump({"settings": {
                "texture_parallel_conversions": {"value": "abc"},
                "rendersize": {"value": 512},
            }}, handle)
        b = self.machine(self.home_b)
        self.assertEqual(4, b.texture_parallel_conversions,
                         "junk from the store reached the attribute "
                         "raw - the clamp was bypassed")
        self.assertEqual(512, b.rendersize,
                         "an invalid neighbour discarded the good value "
                         "with it")


class AnUnchangedSaveDoesNotTouchTheStore(SharedPrefsCase):
    """`save()` runs on sidebar use, so the store is not written when no shared key changed."""

    def test_a_second_save_with_nothing_changed_leaves_the_file_alone(self):
        a = self.machine(self.home_a)
        a.rendersize = 512
        a.save()
        library_db.flush()
        store_path = os.path.join(self.lib, STORE)
        before = os.stat(store_path).st_mtime_ns
        a.save()
        library_db.flush()
        self.assertEqual(before, os.stat(store_path).st_mtime_ns,
                         "an unchanged save rewrote DataBase.json - the "
                         "UNCHANGED check is not applied to the "
                         "store write")


class EverySharedRowIsReread(SharedPrefsCase):
    """Preferences re-reads every shared setting's row when the library changes."""

    def test_every_shared_setting_preferences_shows_is_reread(self):
        from amaze.prefs import persistence
        shared = {prop for prop, _attr, _default
                  in persistence.SHARED_KEYS.values() if prop}
        self.assertEqual(
            set(), shared - set(prefs_window.SETTINGS),
            "a shared setting has no row that reads it from Prefs, so it goes on "
            "showing the previous library's value when the library changes")


class EveryRowFollowsAUserOrLibraryChange(SharedPrefsCase):
    """Preferences shows the user and library NOW in use, so a switch toggled next edits theirs."""

    SECOND = {    # the second user's view state, unlike every default
        "enabled_sections": ["material", "code"],
        "sidebar_counts": False,
        "hide_empty_categories": False,
        "icon_line_weight": "feather",
        "debug_mode": True,
    }

    def setUp(self):
        super().setUp()
        from amaze.core import users
        self.prefs = self.machine(self.home_a)
        self.first = users.create(self.prefs, "Cobalt")
        self.second = users.create(self.prefs, "Sienna")
        users.set_current_user(self.prefs, self.first)
        users.set_current_user(self.prefs, self.second)
        for name, value in self.SECOND.items():
            setattr(self.prefs, name, value)
        users.set_current_user(self.prefs, self.first)
        self.assertNotEqual(self.SECOND["enabled_sections"],
                            self.prefs.enabled_sections,
                            "premise: the first user's state is not the second's")
        self.state = prefs_window.AmazePrefsState(self.prefs, pane=None)
        self.reread = []
        self.state.prefsUpdated.connect(lambda: self.reread.append(True))

    def shown(self):
        s = self.state
        return {
            "enabled_sections": [key for key, _label in section_list.SECTIONS
                                 if s.getBool(prefs_window.SECTION + key)],
            "sidebar_counts": s.getBool("sidebar_counts"),
            "hide_empty_categories": s.getBool("hide_empty_categories"),
            "icon_line_weight": s.getPref("icon_line_weight"),
            "debug_mode": s.getBool("debug_mode"),
        }

    def pick_second(self):
        self.state.setPref(prefs_window.USER, self.second)    # what the User row's menu sends
        del self.reread[:]
        self.state.apply()
        self.assertEqual(0, self.state.changeCount, "Apply left the pick pending")
        self.assertTrue(self.reread, "the rows were not told to read their values again")
        self.assertEqual(self.second, self.prefs.library_user,
                         "premise: Apply switched the user")

    def test_picking_a_user_shows_their_settings(self):
        self.pick_second()
        self.assertEqual(self.SECOND, self.shown(),
                         "the rows still show the previous user's settings")

    def test_picking_a_user_redraws_the_tiles_in_their_line_weight(self):
        from amaze.core import tile_icons
        prefs, drawn = self.prefs, []

        class _Model:
            def rerender_tile_icons(self):
                drawn.append(tile_icons.stroke_for(prefs))
                return 0

        class _Pane:
            library = types.SimpleNamespace(serves=lambda _folder: True)

            def tile_icon_models(self):
                return (_Model(),)

        self.state._pane = _Pane()
        self.pick_second()
        self.assertEqual(
            [tile_icons.FEATHER_STROKE_UNITS], drawn,
            "Tile Icon Line shows the picked user's weight while the "
            "tiles keep the previous user's")
        self.state.apply()
        self.assertEqual(1, len(drawn),
                         "the tiles were redrawn with no weight change")

    def test_a_switch_toggled_after_a_pick_edits_the_picked_users_list(self):
        self.pick_second()
        self.state.setPref(prefs_window.SECTION + "code", "0")    # what the Code switch sends
        self.state.apply()
        self.assertEqual(["material"], self.prefs.enabled_sections,
                         "the toggle saved the previous user's list as "
                         "the picked user's")

    def test_a_library_change_rereads_the_shared_and_per_user_rows(self):
        from amaze.core import users
        other = tempfile.mkdtemp(prefix="amaze_shared_lib_other_")
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        library_db.flush()
        shutil.copy(os.path.join(self.lib, STORE), other)
        elsewhere = prefs_mod.Prefs()
        elsewhere.path = self.home_b
        elsewhere.library_user = "u-elsewhere"
        elsewhere.dir = other + "/"
        elsewhere.rendersize = 512
        elsewhere.save()
        test_support.reset_database_singletons()
        class _Panel:
            def serves(self, _folder):
                return False

            def takes_library(self, _folder):
                return True

            def open_library(self):
                return True

            def tile_icon_models(self):
                return ()

        self.state._panel = _Panel()
        self.state.pick_library(other + "/")
        self.pick_second()
        self.assertEqual("512", self.state.getPref("rendersize"),
                         "a shared row kept the previous library's value")
        self.assertEqual(self.SECOND, self.shown(),
                         "a per-user row kept the previous user's value")


class AMachineRunningBeforeAChangeReadsIt(SharedPrefsCase):
    """r5: B, open since before A's change, takes it at its next save instead of writing its own back."""

    def setUp(self):
        super().setUp()
        self._tables = {"A": {}, "B": {}}    # two processes share no open store

    def on(self, machine):
        """That machine's own open databases: two processes share none, and save at once."""
        return mock.patch.object(library_db, "_libraries", self._tables[machine])

    def stored(self, key):
        return self.store_doc()["prefs"][key]["value"]

    def both_open(self):
        with self.on("A"):
            a = self.machine(self.home_a)
            a.save()
        with self.on("B"):
            b = self.machine(self.home_b)
            b.save()
        return a, b

    def test_a_save_after_refresh_all_keeps_the_peers_value(self):
        a, b = self.both_open()
        with self.on("A"):
            a.rendersize = 512
            a.save()
        with self.on("B"):
            model_registry.refresh_all(b)    # the panel shown, Preferences opened
            b.sidebar_width = 300
            b.save()
        self.assertEqual(512, self.stored("rendersize"), "B wrote its own value back")
        self.assertEqual(512, b.rendersize, "B still returns its own value")

    def test_with_no_refresh_all_the_second_save_keeps_it_too(self):
        a, b = self.both_open()
        with self.on("A"):
            a.rendersize = 1024
            a.save()
        with self.on("B"):
            b.path_style = "absolute"
            b.save()    # its commit merges A's value in
            self.assertEqual(1024, b.rendersize, "the save that merged A's value left B on its own value")
            b.show_notes = True
            b.save()
        self.assertEqual(1024, self.stored("rendersize"), "B's second save reverted A's change")
        self.assertEqual("absolute", self.stored("path_style"), "B's own change was lost")
        with self.on("A"):
            a.rendersize = 768
            with test_support.captured_log() as log:
                a.save()
        self.assertEqual([], log.messages("alert"),
                         "A's next change was reported as a conflict with B")

    def test_a_value_saved_here_follows_a_later_peer_change(self):
        a, b = self.both_open()
        with self.on("B"):
            b.rendersize = 300
            b.save()
        with self.on("A"):
            model_registry.refresh_all(a)
            a.sidebar_width = 200
            a.save()
            a.rendersize = 512
            a.save()
        with self.on("B"):
            model_registry.refresh_all(b)
            b.sidebar_width = 300
            b.save()
        self.assertEqual(512, self.stored("rendersize"),
                         "B wrote back the value it pushed before A's change")

    def test_preferences_shows_the_peers_value(self):
        a, b = self.both_open()
        with self.on("A"):
            a.rendersize = 512
            a.save()
        with self.on("B"):
            state = prefs_window.AmazePrefsState(b, pane=None)    # the window re-reads the stores
        self.assertEqual("512", state.getPref("rendersize"),
                         "Preferences shows the value this machine started with")


if __name__ == "__main__":
    unittest.main()
