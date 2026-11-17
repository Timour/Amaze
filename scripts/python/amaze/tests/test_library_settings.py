"""`DataBase.json`'s own sections: the library's version, its policy, shared settings and marks."""

import json
import os
import shutil
import sys
import tempfile
import types
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import guard, library_db, library_files, library_policy, library_settings  # noqa: E402
from amaze.prefs import prefs as prefs_mod  # noqa: E402
from amaze.tests import test_support  # noqa: E402


class _Library(unittest.TestCase):

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.dir = tempfile.mkdtemp(prefix="amaze_settings_lib_") + os.sep
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.prefs = types.SimpleNamespace(dir=self.dir, library_user=test_support.FIXTURE_USER)

    def master(self) -> dict:
        with open(os.path.join(self.dir, library_files.MASTER), encoding="utf-8") as handle:
            return json.load(handle)


class TheLibraryVersionTest(_Library):

    def test_a_new_library_is_created_at_this_version_and_reads_as_2_0(self):
        self.assertTrue(prefs_mod.create_library(self.dir))
        self.assertEqual(library_policy.LIBRARY_VERSION, library_settings.library_version(self.dir))
        self.assertEqual("2.0", library_settings.version_label(
            library_settings.library_version(self.dir)))

    def test_the_format_shown_counts_every_step_of_the_three_numbers(self):
        from amaze import branding
        from amaze.core import asset_record
        self.assertEqual((library_policy.LIBRARY_VERSION, branding.LIBRARY_FORMAT,
                          asset_record.FORMAT), library_settings.THIS_AMAZE,
                         "library_policy.py names a number the code does not write")
        version, database, record = library_policy.FORMAT_2_0
        for found, shown in (((version, database, record), "2.0"),
                             ((version, database + 1, record), "2.1"),
                             ((version + 1, database, record), "2.1"),
                             ((version, database, record + 1), "2.1"),
                             ((version + 1, database + 1, record), "2.2"),
                             ((version + 1, database + 1, record + 2), "2.4"),
                             ((version, 0, 0), "2.0"), ((version - 1, 0, 0), "3")):
            self.assertEqual(shown, library_settings.version_label(found), found)
        self.assertEqual("2.1", library_settings.version_label(version + 1))

    def test_the_three_numbers_are_read_from_the_policy_and_default_to_2_0(self):
        self.assertTrue(prefs_mod.create_library(self.dir))
        self.assertEqual(library_policy.FORMAT_2_0, library_settings.library_formats(self.dir))
        held = guard.Guard(self.dir)
        reading = held.read(library_files.MASTER)
        change = held.change("")
        change.put(reading.ticket, dict(reading.document, policy={"library": {
            "version": 4, "database": 6, "record": 2}}))
        change.commit()
        self.assertEqual((4, 6, 2), library_settings.library_formats(self.dir))
        self.assertEqual("2.2", library_settings.version_label(
            library_settings.library_formats(self.dir)))

    def test_a_library_already_at_this_amazes_numbers_is_not_written_at_open(self):
        from amaze.actions import library as library_actions
        self.assertTrue(prefs_mod.create_library(self.dir))
        before = self.master()
        self.assertFalse(library_actions.update(self.prefs))
        self.assertEqual(before, self.master())

    def test_an_older_library_reads_as_version_0(self):
        with open(os.path.join(self.dir, "policy.json"), "w", encoding="utf-8") as handle:
            json.dump({"library_version": 3}, handle)
        with open(os.path.join(self.dir, "library.json"), "w", encoding="utf-8") as handle:
            json.dump({"assets": []}, handle)
        self.assertEqual(0, library_settings.library_version(self.dir))

    def test_an_empty_folder_has_no_version(self):
        self.assertEqual(0, library_settings.library_version(self.dir))


class ThePolicyTest(_Library):

    def test_overwrite_is_allowed_until_the_library_policy_forbids_it(self):
        self.assertTrue(library_settings.allow_overwrite(self.prefs))
        self.assertTrue(library_settings.set_allow_overwrite(self.prefs, False))
        self.assertFalse(library_settings.allow_overwrite(self.prefs))
        self.assertFalse(library_settings.allow_overwrite(self.dir), "the folder's value differs")
        self.assertEqual({"value": False}, {
            key: value for key, value in self.master()["policy"]["allow_overwrite"].items()
            if not key.startswith("_")})

    def test_an_unreadable_policy_returns_false(self):
        with open(os.path.join(self.dir, library_files.MASTER), "w", encoding="utf-8") as handle:
            handle.write("{ ruined")
        self.assertFalse(library_settings.allow_overwrite(self.prefs))
        self.assertFalse(library_settings.set_allow_overwrite(self.prefs, True))


class SharedSettingsAndMarksTest(_Library):

    def test_settings_are_one_value_per_key_and_clear_removes_them(self):
        self.assertTrue(library_settings.set_values(self.prefs, {"rendersize": 512,
                                                                 "geometry_bg": "grey"}))
        self.assertEqual({"rendersize": 512, "geometry_bg": "grey"},
                         library_settings.all_values(self.prefs))
        self.assertEqual(512, library_settings.value_of(self.prefs, "rendersize"))
        library_settings.clear(self.prefs, ["rendersize"])
        self.assertEqual("absent", library_settings.value_of(self.prefs, "rendersize", "absent"))
        with self.assertRaises(TypeError):
            library_settings.set_values(self.prefs, {"bad": [1, 2]})

    def test_with_nobody_picked_nothing_is_kept(self):
        nobody = types.SimpleNamespace(dir=self.dir, library_user="")
        library_db.library_for(nobody)
        self.assertFalse(library_settings.takes_writes(nobody))
        self.assertFalse(library_settings.set_values(nobody, {"rendersize": 64}))

    def test_a_mark_is_kept_once(self):
        self.assertFalse(library_settings.marked(self.prefs, "code_starter_v1"))
        self.assertTrue(library_settings.mark(self.prefs, "code_starter_v1", added=3))
        test_support.reset_database_singletons()
        self.assertTrue(library_settings.marked(self.prefs, "code_starter_v1"))


if __name__ == "__main__":
    unittest.main()
