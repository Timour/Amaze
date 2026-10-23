"""Shared settings live with the library: a move of `dir` adopts them. ▸archive/test_prefs_shared.py
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import keyed_store, renderers  # noqa: E402
from amaze.prefs import prefs as prefs_mod   # noqa: E402
from amaze.tests import test_support         # noqa: E402,F401


class SharedPrefsCase(unittest.TestCase):
    """Two machine-homes and one library, like the real pair of Macs."""

    def setUp(self):
        self.home_a = tempfile.mkdtemp(prefix="amaze_shared_a_")
        self.home_b = tempfile.mkdtemp(prefix="amaze_shared_b_")
        self.lib = tempfile.mkdtemp(prefix="amaze_shared_lib_")
        for folder in (self.home_a, self.home_b, self.lib):
            self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        keyed_store.release()
        self.addCleanup(keyed_store.release)

    def machine(self, home):
        """A Prefs the way a session builds one - load settings, then meet the library."""
        p = prefs_mod.Prefs()
        p.path = home
        p.load()
        p.dir = self.lib + "/"
        return p

    def settings_doc(self, home):
        with open(os.path.join(home, "settings.json"),
                  encoding="utf-8") as handle:
            return json.load(handle)

    def store_doc(self):
        with open(os.path.join(self.lib, "prefs.json"),
                  encoding="utf-8") as handle:
            return json.load(handle)


class AChangeReachesTheNextMachine(SharedPrefsCase):
    """Shared means the OTHER machine's session answers with your value, off the library alone."""

    def test_a_saved_change_is_the_next_machines_answer(self):
        a = self.machine(self.home_a)
        a.rendersize = 512
        # OFF, never ON - asserting True passes on the default alone.
        a.renderer_octane_enabled = False
        a.render_on_import = 0    # falsy: the record wrap keeps the delete contract off it
        a.save()
        keyed_store.release()
        b = self.machine(self.home_b)
        self.assertEqual(512, b.rendersize,
                         "machine B still answers its own default - "
                         "the store was not adopted")
        self.assertFalse(b.renderer_octane_enabled,
                         "a renderer flag did not travel")
        self.assertEqual(0, b.render_on_import,
                         "a falsy shared value did not survive")


class TheFlatSpellingsRetire(SharedPrefsCase):
    """`settings.json` keeps bootstrap and the copy - the old flat keys are dropped by the same save that writes their values to safety."""

    def test_settings_json_carries_the_copy_not_the_flat_keys(self):
        a = self.machine(self.home_a)
        a.rendersize = 512
        a.save()
        doc = self.settings_doc(self.home_a)
        self.assertNotIn(
            "rendersize", doc,
            "the flat spelling is still written - two homes for one "
            "value is the drift this line exists to remove")
        self.assertEqual(
            512, doc.get("shared_settings", {}).get("rendersize"),
            "the last-known copy is missing, so an unreachable "
            "library would reset every shared setting")
        self.assertIn("directory", doc,
                      "bootstrap must stay flat - it is how the "
                      "library is found at all")

    def test_an_old_flat_file_loads_and_the_first_save_moves_it(self):
        """The migration - flat values are the load fallback, and one ordinary save carries them into the store and the copy."""
        with open(os.path.join(self.home_a, "settings.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"directory": self.lib + "/",
                       "rendersize": 300,
                       "renderer_octane": False}, handle)
        p = prefs_mod.Prefs()
        p.path = self.home_a
        p.load()
        self.assertEqual(300, p.rendersize,
                         "the flat value no longer loads - the "
                         "migration source was dropped before the "
                         "migration ran")
        self.assertFalse(p.renderer_octane_enabled)
        p.save()
        raw = self.store_doc()["prefs"]
        self.assertEqual(300, raw.get("rendersize", {}).get("value"),
                         "the first save did not seed the store")
        doc = self.settings_doc(self.home_a)
        self.assertNotIn("rendersize", doc)
        self.assertEqual(
            300, doc.get("shared_settings", {}).get("rendersize"))


class TheCopyServesAnUnreachableLibrary(SharedPrefsCase):
    """The library is the truth and the copy opens the panel when the share is down - losing the copy is the one outcome it exists to prevent."""

    def test_values_survive_the_library_being_gone(self):
        a = self.machine(self.home_a)
        a.rendersize = 512
        a.save()
        shutil.rmtree(self.lib)
        keyed_store.release()
        p = prefs_mod.Prefs()
        p.path = self.home_a
        p.load()
        self.assertEqual(512, p.rendersize,
                         "the copy did not serve with the library "
                         "unreachable")
        p.save()          # must not raise, and must not lose the copy
        doc = self.settings_doc(self.home_a)
        self.assertEqual(
            512, doc.get("shared_settings", {}).get("rendersize"),
            "a save without the library blanked the copy")

    def test_a_latched_store_leaves_attributes_and_copy_alone(self):
        a = self.machine(self.home_a)
        a.rendersize = 512
        a.save()
        store_path = os.path.join(self.lib, "prefs.json")
        with open(store_path, "w", encoding="utf-8") as handle:
            handle.write('{"prefs": {"rendersize"')      # truncated
        with open(store_path, "rb") as handle:
            broken = handle.read()
        keyed_store.release()
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
                             "the latch exists so evidence survives")
        doc = self.settings_doc(self.home_a)
        self.assertEqual(
            32, doc.get("shared_settings", {}).get("rendersamples"),
            "the session's change was not kept locally while the "
            "store refused")


class TheLibraryIsAdoptedWhenItArrives(SharedPrefsCase):
    """`dir` can be set long after settings load, and that moment must ADOPT, or the first save pushes this machine's defaults over everyone's answers."""

    def test_pointing_dir_at_a_library_adopts_without_a_load(self):
        a = self.machine(self.home_a)
        a.rendersize = 512
        a.save()
        keyed_store.release()
        fresh = prefs_mod.Prefs()
        fresh.path = self.home_b       # no settings.json, no load()
        fresh.dir = self.lib + "/"
        self.assertEqual(512, fresh.rendersize,
                         "setting `dir` did not adopt the store - a "
                         "fresh install would clobber the library's "
                         "settings on its first save")

    def test_junk_in_the_store_does_not_poison_a_clamped_setting(self):
        """The store's normaliser types the RECORD, never the value's meaning - a hand-edit can put a string where a size belongs, so the adopt must route through the same validation load uses."""
        with open(os.path.join(self.lib, "prefs.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"prefs": {
                "ram_cache_mb": {"value": "abc"},
                "rendersize": {"value": 512},
            }}, handle)
        b = self.machine(self.home_b)
        self.assertEqual(256, b.ram_cache_mb,
                         "junk from the store reached the attribute "
                         "raw - the clamp was bypassed")
        self.assertEqual(512, b.rendersize,
                         "a junk neighbour took the good value down "
                         "with it")


class AnUnchangedSaveDoesNotTouchTheStore(SharedPrefsCase):
    """`save()` runs from ordinary sidebar use, so the push must collapse to nothing when no shared key moved."""

    def test_a_second_save_with_nothing_changed_leaves_the_file_alone(self):
        a = self.machine(self.home_a)
        a.rendersize = 512
        a.save()
        store_path = os.path.join(self.lib, "prefs.json")
        before = os.stat(store_path).st_mtime_ns
        a.save()
        self.assertEqual(before, os.stat(store_path).st_mtime_ns,
                         "an unchanged save rewrote prefs.json - the "
                         "UNCHANGED collapse is not reaching the "
                         "push")


class TheTestLibrarySwitchKeepsEachLibrarysSettings(SharedPrefsCase):
    """Test Library moves what `dir` answers, through the Preferences switch a user flips."""

    def setUp(self):
        super().setUp()
        folder = tempfile.mkdtemp(prefix="amaze_shared_test_lib_")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        ok, what = prefs_mod.seed_test_folder(folder)
        self.assertTrue(ok, what)
        self.test_lib = prefs_mod.test_library_dir(folder)
        self.prefs = self.machine(self.home_a)
        self.prefs.rendersize = 300
        self.prefs.save()
        self.prefs.test_dir = folder
        from amaze.dialogs import prefs_dialog
        self.dialog = prefs_dialog.PrefsDialog(self.prefs, panel=None)
        self.addCleanup(self.dialog.deleteLater)

    def switch_on(self):
        self.dialog.set_test_mode(True)
        self.assertEqual(self.test_lib, self.prefs.dir,
                         "premise: Test Library is on")

    def real_bytes(self):
        with open(os.path.join(self.lib, "prefs.json"), "rb") as handle:
            return handle.read()

    def stored_in_test_lib(self, key):
        with open(os.path.join(self.test_lib, "prefs.json"),
                  encoding="utf-8") as handle:
            return json.load(handle)["prefs"][key]["value"]

    def test_switching_off_leaves_the_real_library_alone(self):
        self.switch_on()
        self.dialog.line_rendersize.setValue(512)
        self.prefs.save()
        before = self.real_bytes()
        self.dialog.set_test_mode(False)
        self.assertEqual(
            before, self.real_bytes(),
            "a setting changed in the test library was written into the "
            "real library when Test Library was switched off")
        self.assertEqual(300, self.prefs.rendersize,
                         "the session still answers the test library's "
                         "setting after switching back")
        self.assertEqual(300, self.dialog.line_rendersize.value(),
                         "Preferences still shows the test library's value")
        self.assertEqual(512, self.stored_in_test_lib("rendersize"))

    def test_an_unsaved_change_lands_in_the_library_it_was_made_in(self):
        self.switch_on()
        self.dialog.line_rendersize.setValue(512)
        before = self.real_bytes()
        self.dialog.set_test_mode(False)
        self.assertEqual(before, self.real_bytes(),
                         "the unsaved change went into the real library")
        self.assertEqual(
            512, self.stored_in_test_lib("rendersize"),
            "the change made with Test Library on was lost instead of "
            "kept in the test library")

    def test_switching_on_shows_the_test_librarys_own_settings(self):
        other = prefs_mod.Prefs()
        other.path = self.home_b
        other.dir = self.test_lib
        other.rendersize = 512
        other.save()
        keyed_store.release()
        before = self.real_bytes()
        self.switch_on()
        self.assertEqual(512, self.prefs.rendersize,
                         "the session answers the real library's setting "
                         "with Test Library on")
        self.assertEqual(512, self.dialog.line_rendersize.value(),
                         "Preferences shows the real library's value")
        self.assertEqual(512, self.stored_in_test_lib("rendersize"),
                         "switching on wrote the real library's setting "
                         "over the test library's")
        self.assertEqual(before, self.real_bytes())

    def test_every_shared_setting_preferences_shows_is_reread(self):
        from amaze.prefs import persistence
        reread = {prop for _row, prop in self.dialog._SHARED_ROWS}
        reread |= set(self.dialog._renderer_boxes)
        reread |= {renderer.samples for renderer in renderers.ALL
                   if renderer.key in self.dialog._samples_spins}
        shared = {prop for prop, _attr, _default
                  in persistence.SHARED_KEYS.values() if prop}
        self.assertEqual(
            shared, reread,
            "a shared setting's row is not re-read when the library "
            "changes, so it goes on showing the previous library's value")


class EveryRowFollowsAUserOrLibraryChange(SharedPrefsCase):
    """Preferences shows the user and library NOW in use, so a switch toggled next edits theirs."""

    SECOND = {    # the second user's view state, unlike every default
        "enabled_sections": ["material", "code"],
        "sidebar_counts": False,
        "hide_empty_categories": False,
        "icon_line_weight": "feather",
        "scroll_speed": 1.5,
        "debug_mode": True,
    }

    def setUp(self):
        super().setUp()
        from amaze.core import users
        from amaze.dialogs import prefs_dialog
        self.prefs = self.machine(self.home_a)
        self.first = users.create(self.prefs, "Cobalt")
        self.second = users.create(self.prefs, "Sienna")
        users.adopt(self.prefs, self.first)
        users.adopt(self.prefs, self.second)
        for name, value in self.SECOND.items():
            setattr(self.prefs, name, value)
        users.adopt(self.prefs, self.first)
        self.assertNotEqual(self.SECOND["enabled_sections"],
                            self.prefs.enabled_sections,
                            "premise: the first user's state is not the second's")
        self.dialog = prefs_dialog.PrefsDialog(self.prefs, panel=None)
        self.addCleanup(self.dialog.deleteLater)

    def shown(self):
        d = self.dialog
        return {
            "enabled_sections": [key for key, box in d._section_boxes.items()
                                 if box.isChecked()],
            "sidebar_counts": d._cbx_sidebar_counts.isChecked(),
            "hide_empty_categories": d._cbx_hide_empty.isChecked(),
            "icon_line_weight": d._combo_icon_weight.currentData(),
            "scroll_speed": d.spin_scroll_speed.value() / 100.0,
            "debug_mode": d._cbx_debug.isChecked(),
        }

    def pick_second(self):
        combo = self.dialog.cbb_library_user
        combo.setCurrentIndex(combo.findData(self.second))
        self.assertTrue(self.dialog.apply_library())
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

        class _Panel:
            def serves(self, _folder):
                return True

            def tile_icon_models(self):
                return (_Model(),)

        self.dialog._panel = _Panel()
        self.pick_second()
        self.assertEqual(
            [tile_icons.FEATHER_STROKE_UNITS], drawn,
            "Tile Icon Line shows the picked user's weight while the "
            "tiles keep the previous user's")
        self.dialog._sync_rows()
        self.assertEqual(1, len(drawn),
                         "the tiles were redrawn with no weight change")

    def test_a_switch_toggled_after_a_pick_edits_the_picked_users_list(self):
        self.pick_second()
        self.dialog._section_boxes["code"].setChecked(False)
        self.assertEqual(["material"], self.prefs.enabled_sections,
                         "the toggle saved the previous user's list as "
                         "the picked user's")

    def test_a_library_change_rereads_the_shared_and_per_user_rows(self):
        from amaze.core import users
        other = tempfile.mkdtemp(prefix="amaze_shared_lib_other_")
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        shutil.copy(os.path.join(self.lib, users.USERS_FILE), other)
        elsewhere = prefs_mod.Prefs()
        elsewhere.path = self.home_b
        elsewhere.dir = other + "/"
        elsewhere.rendersize = 512
        elsewhere.save()
        keyed_store.release()
        class _Panel:
            def serves(self, _folder):
                return False

            def takes_library(self, _folder):
                return True

            def open_library(self):
                return True

            def tile_icon_models(self):
                return ()

        self.dialog._panel = _Panel()
        self.dialog.pick_library(other + "/")
        combo = self.dialog.cbb_library_user
        combo.setCurrentIndex(combo.findData(self.second))
        self.assertTrue(self.dialog.apply_library())
        self.assertEqual(512, self.dialog.line_rendersize.value(),
                         "a shared row kept the previous library's value")
        self.assertEqual(self.SECOND, self.shown(),
                         "a per-user row kept the previous user's value")


if __name__ == "__main__":
    unittest.main()
