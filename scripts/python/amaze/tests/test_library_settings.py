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

from amaze.core import library_db, library_files, library_policy, library_settings  # noqa: E402
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

    def test_a_new_library_is_born_at_this_version_and_reads_as_2_0(self):
        self.assertTrue(prefs_mod.create_library(self.dir))
        self.assertEqual(library_policy.LIBRARY_VERSION, library_settings.library_version(self.dir))
        self.assertEqual("2.0", library_settings.version_label(
            library_settings.library_version(self.dir)))

    def test_an_older_library_reads_its_own_number_and_needs_converting(self):
        with open(os.path.join(self.dir, "policy.json"), "w", encoding="utf-8") as handle:
            json.dump({"library_version": 3}, handle)
        with open(os.path.join(self.dir, "library.json"), "w", encoding="utf-8") as handle:
            json.dump({"assets": []}, handle)
        self.assertEqual(3, library_settings.library_version(self.dir))
        self.assertEqual("3", library_settings.version_label(3))

    def test_an_empty_folder_has_no_version(self):
        self.assertEqual(0, library_settings.library_version(self.dir))


class ThePolicyTest(_Library):

    def test_overwrite_is_allowed_until_the_library_says_otherwise(self):
        self.assertTrue(library_settings.allow_overwrite(self.prefs))
        self.assertTrue(library_settings.set_allow_overwrite(self.prefs, False))
        self.assertFalse(library_settings.allow_overwrite(self.prefs))
        self.assertFalse(library_settings.allow_overwrite(self.dir), "the folder's answer differs")
        self.assertEqual({"value": False}, {
            key: value for key, value in self.master()["policy"]["allow_overwrite"].items()
            if not key.startswith("_")})

    def test_a_policy_that_does_not_read_answers_no(self):
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
