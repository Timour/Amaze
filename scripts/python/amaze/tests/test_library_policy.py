"""
The library's own settings - the ones that must not live in prefs.

prefs.Prefs is per-user and per-machine and never synced, so a safety
switch kept there protects its owner and nobody else while looking like
protection. These live beside library.json and travel with the library.
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

from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401
from amaze.core import library_policy  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401


class PolicyFileTest(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_policy_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = library_policy.path_for(self.dir)

    def test_a_byte_order_mark_is_read_not_fail_closed(self):
        """policy.json is the one library file a user is INVITED to
        hand-edit, and Windows Notepad prepends a BOM - which made the
        parse raise, and fail-closed then read a healthy permissive
        policy as the most restrictive one: Update Existing refused
        library-wide over three invisible bytes. utf-8-sig, like every
        other reader in the package (keyed_store says why)."""
        with open(self.path, "w", encoding="utf-8-sig") as handle:
            json.dump({"allow_overwrite": True,
                       "version": library_policy.POLICY_VERSION}, handle)
        self.assertTrue(
            library_policy.allow_overwrite(self.dir),
            "a Notepad BOM read as a broken policy file")

    def _write(self, text):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(text)

    # -- the absent case ------------------------------------------------
    def test_absent_means_allow(self):
        """A library written before this existed must keep working."""
        self.assertTrue(library_policy.allow_overwrite(self.dir))

    # -- fail closed ----------------------------------------------------
    def test_an_unreadable_policy_is_read_as_the_STRICTEST_setting(self):
        """"I could not check" must never mean "go ahead"."""
        self._write('{"allow_overwrite": true, ')       # truncated
        self.assertFalse(
            library_policy.allow_overwrite(self.dir),
            "a policy file we could not parse was read permissively")

    def test_a_policy_that_is_not_an_object_fails_closed(self):
        self._write('["allow_overwrite"]')
        self.assertFalse(library_policy.allow_overwrite(self.dir))

    # -- ordinary round trip --------------------------------------------
    def test_it_round_trips(self):
        self.assertTrue(library_policy.set_allow_overwrite(self.dir, False))
        self.assertFalse(library_policy.allow_overwrite(self.dir))
        self.assertTrue(library_policy.set_allow_overwrite(self.dir, True))
        self.assertTrue(library_policy.allow_overwrite(self.dir))

    def test_it_is_stored_in_the_LIBRARY_not_in_prefs(self):
        library_policy.set_allow_overwrite(self.dir, False)
        self.assertTrue(
            os.path.isfile(os.path.join(self.dir, "policy.json")),
            "the setting did not land in the library folder - a "
            "per-user copy protects nobody else")

    def test_it_is_its_own_file_not_a_key_in_library_json(self):
        """Flipping a boolean must not mean rewriting 548 asset
        records, and reading it must not mean parsing 355KB."""
        library_policy.set_allow_overwrite(self.dir, False)
        self.assertNotEqual(
            library_policy.path_for(self.dir),
            os.path.join(self.dir, "library.json"))

    def test_it_records_a_version(self):
        library_policy.set_allow_overwrite(self.dir, False)
        with open(self.path, encoding="utf-8") as handle:
            self.assertIn("version", json.load(handle))

    def test_an_unreadable_file_is_preserved_before_being_replaced(self):
        self._write("{ this is not json")
        library_policy.set_allow_overwrite(self.dir, False)
        self.assertTrue(
            os.path.exists(self.path + ".unreadable"),
            "the unreadable policy was replaced with no copy kept")

    def test_a_missing_library_folder_reports_failure(self):
        """Never a silent no-op: the caller shows the switch."""
        self.assertFalse(
            library_policy.set_allow_overwrite(
                os.path.join(self.dir, "nope"), False))

    def test_unknown_keys_survive_a_write(self):
        """A newer build's setting must not be erased by an older one."""
        self._write(json.dumps({"allow_overwrite": True,
                                "some_future_setting": 42}))
        library_policy.set_allow_overwrite(self.dir, False)
        with open(self.path, encoding="utf-8") as handle:
            self.assertEqual(42, json.load(handle)["some_future_setting"])


class OverwriteIsGatedInTheMODELTest(unittest.TestCase):
    """The dialog also stops offering Overwrite, but the refusal has to
    be where every caller passes - a UI check is a suggestion."""

    def test_update_asset_content_consults_the_policy(self):
        import re
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "core", "library.py")
        with open(path, encoding="utf-8") as handle:
            code = handle.read()
        start = code.find("def update_asset_content")
        end = code.find("\n    def ", start + 10)
        body = re.sub(r"#.*", "", code[start:end])
        self.assertIn("library_policy.allow_overwrite", body,
                      "the model does not check the policy")
        gate = body.find("library_policy.allow_overwrite")
        write = body.find("save_node(")
        self.assertGreater(write, -1)
        self.assertLess(gate, write,
                        "the policy is checked AFTER the files are written")

    def test_the_dialog_does_not_offer_what_the_policy_forbids(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "panel", "panel.py")
        with open(path, encoding="utf-8") as handle:
            code = handle.read()
        self.assertIn("may_overwrite = library_policy.allow_overwrite", code)
        self.assertIn('buttons = ("Save New", "Cancel")', code,
                      "the Save Version button is still offered when the "
                      "library forbids it - an option that always fails "
                      "is worse than one that is not there")


class BrokenPolicyShapesFailClosedTest(unittest.TestCase):
    """A dangling symlink, a directory in the file's place, and the
    string "false" all read as the PERMISSIVE default before this -
    contradicting the module's own fail-closed contract, reproduced
    live against the real module."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_policy_shape_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = library_policy.path_for(self.dir)

    def test_a_dangling_symlink_fails_closed(self):
        os.symlink(os.path.join(self.dir, "not-there.json"), self.path)
        self.assertFalse(
            library_policy.allow_overwrite(self.dir),
            "a policy that is a link to nothing read as permissive")

    def test_a_directory_in_the_files_place_fails_closed(self):
        os.mkdir(self.path)
        self.assertFalse(
            library_policy.allow_overwrite(self.dir),
            "a folder where policy.json should be read as permissive")

    def test_the_string_false_fails_closed(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({"allow_overwrite": "false"}, handle)
        self.assertFalse(
            library_policy.allow_overwrite(self.dir),
            'bool("false") is True - the most natural way to hand-edit '
            "the file wrong read as permissive")

    def test_the_string_no_fails_closed(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({"allow_overwrite": "no"}, handle)
        self.assertFalse(library_policy.allow_overwrite(self.dir))

    def test_genuinely_absent_still_allows(self):
        """The permissive default is CORRECT for a library that predates
        the mechanism - failing closed there would freeze every old
        library for no reason."""
        self.assertTrue(library_policy.allow_overwrite(self.dir))

    def test_a_real_false_still_works(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({"allow_overwrite": False}, handle)
        self.assertFalse(library_policy.allow_overwrite(self.dir))

    def test_a_write_leaves_a_restore_point(self):
        self.assertTrue(library_policy.set_allow_overwrite(self.dir, False))
        self.assertTrue(library_policy.set_allow_overwrite(self.dir, True))
        self.assertTrue(
            os.path.exists(self.path + ".bak-first"),
            "policy.json still has no backup tier")


if __name__ == "__main__":
    unittest.main()
