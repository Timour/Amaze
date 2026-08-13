"""The shared settings LIVE WITH THE LIBRARY (ROADMAP line 22, stage D).

Nineteen keys - the library layout quartet, the render settings, the
renderer flags, the throughput numbers, the geometry look and
path_style - are ONE answer for everyone who opens the library
(ROADMAP line 22 carries the decision and its scoping).
The truth is `prefs.json` through the Shared Settings store;
settings.json keeps a last-known COPY under `"shared_settings"`, which
is what loads when the library is unreachable; the flat spellings are
retired.

The choreography, pinned here because every piece of it is a way the
move can silently not happen:

* load() and the `dir` setter ADOPT the store's answers into the
  attributes - the two moments a Prefs meets a library, and both come
  before any user edit in every real flow, so an adopted value can
  never eat an edit;
* save() PUSHES the attributes through ONE batch write, gated on the
  library directory existing and the store taking writes - reads stay
  plain attribute reads, so a setter is visible to the very next read
  with no store round-trip in between;
* the copy serves when the library cannot, and a latched store leaves
  both the attributes and the copy alone.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import keyed_store           # noqa: E402
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
        """A Prefs the way a session builds one: load settings, then
        meet the library."""
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
    """The headline: shared means the OTHER machine's session answers
    with your value, off the library alone."""

    def test_a_saved_change_is_the_next_machines_answer(self):
        a = self.machine(self.home_a)
        a.rendersize = 512
        a.renderer_mantra_enabled = True
        a.save()
        # The machine boundary: nothing in memory may carry over.
        keyed_store.release()
        b = self.machine(self.home_b)
        self.assertEqual(512, b.rendersize,
                         "machine B still answers its own default - "
                         "the store was not adopted")
        self.assertTrue(b.renderer_mantra_enabled,
                        "a renderer flag did not travel")

    def test_a_falsy_value_survives_the_trip(self):
        """False, 0 and "" are legitimate choices, and the record wrap
        exists so the engine's delete contract cannot eat them."""
        a = self.machine(self.home_a)
        a.render_on_import = 0
        a.renderer_redshift_enabled = False
        a.save()
        keyed_store.release()
        b = self.machine(self.home_b)
        self.assertEqual(0, b.render_on_import,
                         "a falsy shared value did not survive")
        self.assertFalse(b.renderer_redshift_enabled,
                         "False read back as the default True")


class TheFlatSpellingsRetire(SharedPrefsCase):
    """settings.json keeps bootstrap + the copy; the 19 old flat keys
    are dropped by the same save that writes their values to safety."""

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
        """The migration: flat values are the load fallback, and one
        ordinary save carries them into the store and the copy."""
        with open(os.path.join(self.home_a, "settings.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"directory": self.lib + "/",
                       "rendersize": 300,
                       "renderer_mantra": True}, handle)
        p = prefs_mod.Prefs()
        p.path = self.home_a
        p.load()
        self.assertEqual(300, p.rendersize,
                         "the flat value no longer loads - the "
                         "migration source was dropped before the "
                         "migration ran")
        self.assertTrue(p.renderer_mantra_enabled)
        p.save()
        raw = self.store_doc()["prefs"]
        self.assertEqual(300, raw.get("rendersize", {}).get("value"),
                         "the first save did not seed the store")
        doc = self.settings_doc(self.home_a)
        self.assertNotIn("rendersize", doc)
        self.assertEqual(
            300, doc.get("shared_settings", {}).get("rendersize"))


class TheCopyServesAnUnreachableLibrary(SharedPrefsCase):
    """The File section's contract, applied to scalars: the library is
    the truth, the copy is what opens the panel when the share is
    down, and losing the copy is the one outcome the copy exists to
    prevent."""

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
    """`dir` can be set long after settings load - a fresh install
    joining an existing library picks the folder in a dialog. That
    moment must adopt, or the first save pushes this machine's
    defaults over everyone's answers."""

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
        """The store's normaliser types the RECORD, not the value's
        meaning - a hand-edit can put a string where a size belongs,
        and the adopt must route through the same validation load
        uses."""
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
    """save() runs from ordinary sidebar use; the push must collapse
    to nothing when no shared key moved, or every favourite toggled
    would fsync the library's prefs.json."""

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


if __name__ == "__main__":
    unittest.main()
