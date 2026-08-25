"""The library's own settings, the ones that must NOT live in prefs: prefs.Prefs is per-user, per-machine and never synced, so a safety switch kept there protects its owner and nobody else while looking like protection - these live beside library.json and travel with the library."""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # BEFORE the app exists ▸p/first-app-picks-the-platform
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
        """A hand-edited policy.json still parses when the editor left a BOM behind, instead of failing closed library-wide over three invisible bytes."""
        with open(self.path, "w", encoding="utf-8-sig") as handle:   # a Windows editor leaves a BOM; utf-8-sig is what every reader in the package uses, and keyed_store says why
            json.dump({"allow_overwrite": True,
                       "version": library_policy.POLICY_VERSION}, handle)
        self.assertTrue(
            library_policy.allow_overwrite(self.dir),
            "a Notepad BOM read as a broken policy file")

    def _write(self, text):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(text)

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
        """The policy is its OWN file: flipping a boolean must not mean rewriting 548 asset records, and reading it must not mean parsing 355KB."""
        library_policy.set_allow_overwrite(self.dir, False)
        self.assertNotEqual(
            library_policy.path_for(self.dir),
            os.path.join(self.dir, "library.json"))   # 355KB parsed to answer one bool

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
    """The refusal has to sit where every caller passes: the dialog also stops offering Overwrite, but a UI check is only a suggestion."""

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
    """Every broken shape of policy.json - a dangling symlink, a directory in its place, a hand-typed string - must read as the STRICTEST setting, not the permissive default."""

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
        """The permissive default is CORRECT for a library that predates the mechanism - failing closed there would freeze every old library for no reason."""
        self.assertTrue(library_policy.allow_overwrite(self.dir))

    def test_a_real_false_still_works(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({"allow_overwrite": False}, handle)
        self.assertFalse(library_policy.allow_overwrite(self.dir))

    def test_a_write_leaves_a_restore_point(self):
        """A policy rewritten a second time leaves a restore point - the write-ONCE case, which is what the product actually produces, has its own test below."""
        self.assertTrue(library_policy.set_allow_overwrite(self.dir, False))
        self.assertTrue(library_policy.set_allow_overwrite(self.dir, True))   # THIS write is the one that snapshots the first
        self.assertTrue(
            os.path.exists(self.path + ".bak-first"),
            "policy.json still has no backup tier")

    def test_a_policy_written_ONCE_leaves_a_restore_point(self):
        """The normal case - turn Overwrite off, never touch it again - must still leave a restore point, even though there was nothing on disk to snapshot."""
        self.assertTrue(library_policy.set_allow_overwrite(self.dir, False))   # the only write the product usually makes
        self.assertTrue(
            os.path.exists(self.path + ".bak-first"),
            "a policy set once has no restore point and nothing saying "
            "it was ever here")   # snapshot_before_write declines an empty copy, so this trace is also the evidence the absence guard below looks for

    def test_a_policy_that_is_momentarily_ABSENT_stays_restrictive(self):
        """Absence means the library predates the mechanism ONLY when nothing says otherwise: with a trace on disk, a policy that is merely late still reads as restrictive, like every other branch of read()."""
        self.assertTrue(library_policy.set_allow_overwrite(self.dir, False))
        os.remove(self.path)   # a shared library's file can be late - a sync placeholder still arriving, gone the moment the panel reads it and back after
        self.assertFalse(
            library_policy.allow_overwrite(self.dir),
            "an append-only library became writable because its policy "
            "file was not there for an instant")

    def test_a_library_that_never_had_a_policy_is_still_permissive(self):
        """The accept path beside the guard above: absence with NO trace is a library written before the mechanism existed, and it must keep working exactly as it did."""
        self.assertTrue(library_policy.allow_overwrite(self.dir),   # a guard that fires when there is nothing to protect is an outage
                        "a library that never had a policy was refused "
                        "an overwrite")


if __name__ == "__main__":
    unittest.main()
