"""The Shared Settings store: `prefs.json`, everyone's answer.

ROADMAP line 22's library-wide half, landed with the switch OFF:
nothing in the product reads this store yet, so these tests are the
only caller and must pin the contract the flip commits will lean on.

THE ONE SHAPE RULE WORTH A FILE: a value is a RECORD,
`{"value": <scalar>}`, never a bare scalar - the engine reads a falsy
normalise result as the delete contract, so a bare False, 0 or ""
would read back as absent, and all three are legitimate settings.
The round-trip tests below are the proof that survives; sabotage the
wrap and they go red.
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

from amaze.core import keyed_store, library_prefs  # noqa: E402
from amaze.tests import test_support               # noqa: E402,F401


class _Prefs:
    """Only what a store reads: where the library is, and WHO this is.
    The user rides along although THIS store is untagged - a stub
    without one would pass exactly until someone tags the spec."""

    def __init__(self, directory, library_user=""):
        self.dir = directory
        self.library_user = library_user


class SharedSettingsCase(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_libprefs_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.prefs = _Prefs(self.dir)
        keyed_store.release()
        self.addCleanup(keyed_store.release)

    def path(self):
        return os.path.join(self.dir, "prefs.json")

    def read_raw(self):
        with open(self.path(), encoding="utf-8") as handle:
            return json.load(handle)


class TheStoreIsDeclared(SharedSettingsCase):
    """Declaration facts the flip commits will lean on, said once."""

    def test_the_registry_and_the_spec_carry_it(self):
        self.assertIn("prefs.json", keyed_store.filenames(),
                      "the shared settings are not a library file, so "
                      "Repair would not survey them and the restore "
                      "picker would not offer them")
        spec = keyed_store.store_for("prefs.json")
        self.assertFalse(
            spec.user_tagged,
            "shared means SHARED - a user tag here would give every "
            "user a private copy of the library's one answer")
        self.assertTrue(
            spec.survives_forget,
            "a setting is not a property of a folder someone removed")
        self.assertEqual(
            keyed_store.KEY_ID, spec.keyspace,
            "a preference name is an identifier - path-keyed, a folder "
            "move would rewrite it")

    def test_no_two_stores_share_an_alert_key(self):
        """Alert keys are once-per-session, so a shared key means one
        store's report swallows the other's. persistence.py already
        owns "prefs-unreadable" for settings.json - measured before
        this store nearly took the same name."""
        keys = [spec.alert_key for spec in keyed_store.stores()]
        self.assertEqual(len(keys), len(set(keys)),
                         "two stores share an alert key")
        self.assertNotIn("prefs-unreadable", keys,
                         "settings.json raises that key in "
                         "persistence.py - the store must not shadow "
                         "it")


class FalsyScalarsSurviveTheRoundTrip(SharedSettingsCase):
    """The reason values are records. Every entry here is a legitimate
    setting somebody can choose, and every one is falsy."""

    CASES = (False, 0, "", 0.0)

    def test_each_falsy_scalar_reads_back_exactly(self):
        """One key per case - reusing one key would meet the engine's
        equal-value skip (0 == False), which the test below pins as
        its own fact."""
        for probe in self.CASES:
            with self.subTest(value=probe):
                key = "probe-%s" % type(probe).__name__
                self.assertTrue(
                    library_prefs.set_value(self.prefs, key, probe),
                    "the write itself was refused")
                got = library_prefs.value_of(
                    self.prefs, key, default="MISSING")
                self.assertEqual((type(probe), probe), (type(got), got),
                                 "a falsy setting did not survive - "
                                 "the delete contract ate it")

    def test_an_equal_value_rewrite_keeps_the_first_type(self):
        """Engine behaviour, pinned so a change to it is loud: set()
        answers UNCHANGED for a value that compares equal, and 0 ==
        False in Python, so the first-written type wins. Harmless for
        settings - every consumer casts through the prefs setters -
        and worth a red test the day that stops being true."""
        library_prefs.set_value(self.prefs, "flip", False)
        library_prefs.set_value(self.prefs, "flip", 0)
        got = library_prefs.value_of(self.prefs, "flip", "MISSING")
        self.assertEqual((bool, False), (type(got), got),
                         "the equal-value skip changed - update the "
                         "practice wiki entry beside the record wrap")

    def test_false_is_not_collapsed_to_absent_on_disk(self):
        library_prefs.set_value(self.prefs, "render_on_import", False)
        keyed_store.release()
        fresh = library_prefs.value_of(
            self.prefs, "render_on_import", default="MISSING")
        self.assertIs(False, fresh,
                      "False did not survive a re-read from disk")


class TheDoorIsTyped(SharedSettingsCase):

    def test_a_scalar_round_trips_and_absence_answers_the_default(self):
        self.assertEqual(
            256, library_prefs.value_of(self.prefs, "rendersize", 256))
        library_prefs.set_value(self.prefs, "rendersize", 512)
        self.assertEqual(
            512, library_prefs.value_of(self.prefs, "rendersize", 256))
        self.assertEqual(
            {"rendersize": 512}, library_prefs.all_values(self.prefs))

    def test_a_non_scalar_raises_at_the_door(self):
        """The normaliser would junk it and the write would report
        success for a value that reads back absent - so the door
        refuses loudly instead."""
        for junk in ({"a": 1}, [1, 2], None):
            with self.subTest(value=junk):
                with self.assertRaises(TypeError):
                    library_prefs.set_value(self.prefs, "key", junk)
        self.assertFalse(os.path.exists(self.path()),
                         "a refused write still reached disk")


class ClearIsALoudDelete(SharedSettingsCase):

    def test_cleared_settings_leave_the_file_too(self):
        library_prefs.set_value(self.prefs, "rendersize", 512)
        library_prefs.set_value(self.prefs, "rendersamples", 32)
        self.assertTrue(
            library_prefs.clear(self.prefs, ["rendersize"]))
        self.assertEqual(
            "MISSING",
            library_prefs.value_of(self.prefs, "rendersize", "MISSING"))
        raw = self.read_raw()["prefs"]
        self.assertNotIn("rendersize", raw,
                         "cleared in memory, still on disk - the next "
                         "load resurrects it")
        self.assertIn("rendersamples", raw,
                      "clear took a neighbour with it")


class ANewerBuildsRecordSurvives(SharedSettingsCase):
    """A record whose "value" this build cannot read is FOREIGN - held
    aside verbatim and written back, never stripped. An older build
    must not erase what a newer one wrote (the engine's own contract,
    pinned here because this store is where mixed builds meet first:
    every machine that opens the library writes it)."""

    def test_the_unreadable_record_is_written_back_verbatim(self):
        os.makedirs(self.dir, exist_ok=True)
        with open(self.path(), "w", encoding="utf-8") as handle:
            json.dump({"prefs": {
                "future": {"value": [1, 2, 3], "unit": "px"},
                "plain": {"value": 5},
            }}, handle)
        self.assertEqual(
            5, library_prefs.value_of(self.prefs, "plain", 0))
        self.assertEqual(
            "MISSING",
            library_prefs.value_of(self.prefs, "future", "MISSING"),
            "a foreign record leaked through the reader")
        library_prefs.set_value(self.prefs, "plain", 6)
        raw = self.read_raw()["prefs"]
        self.assertEqual({"value": [1, 2, 3], "unit": "px"},
                         raw.get("future"),
                         "this build's save erased a newer build's "
                         "record")

    def test_an_extra_field_beside_value_survives_a_rewrite(self):
        os.makedirs(self.dir, exist_ok=True)
        with open(self.path(), "w", encoding="utf-8") as handle:
            json.dump({"prefs": {
                "rendersize": {"value": 256, "chosen_by": "someone"},
            }}, handle)
        library_prefs.set_value(self.prefs, "other", 1)
        raw = self.read_raw()["prefs"]
        self.assertEqual(
            {"value": 256, "chosen_by": "someone"},
            raw.get("rendersize"),
            "a field a newer build put beside the value was stripped")


class ItWorksWithNobodyPicked(SharedSettingsCase):
    """The store is untagged, so a machine with no user still reads and
    writes it - shared settings are not anybody's."""

    def test_read_and_write_with_a_blank_user(self):
        blank = _Prefs(self.dir, library_user="")
        self.assertTrue(
            library_prefs.set_value(blank, "rendersize", 128))
        self.assertEqual(
            128, library_prefs.value_of(blank, "rendersize", 0))


if __name__ == "__main__":
    unittest.main()
