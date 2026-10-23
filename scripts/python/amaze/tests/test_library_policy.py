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

    def _write(self, text):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(text)

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


class LibraryVersionTest(unittest.TestCase):
    """The library's own version, kept in its policy so every computer reads the same."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_policy_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = library_policy.path_for(self.dir)

    def test_a_library_from_before_versions_is_1(self):
        self.assertEqual(1, library_policy.library_version(self.dir))

    def test_it_round_trips(self):
        self.assertTrue(library_policy.set_library_version(self.dir, 2))
        self.assertEqual(2, library_policy.library_version(self.dir))
        with open(self.path, encoding="utf-8") as handle:
            self.assertEqual(2, json.load(handle)[library_policy.VERSION_KEY])

    def test_it_and_the_other_settings_keep_each_other(self):
        """Merged writes: older Amaze, which knows no version, keeps it when it saves."""
        library_policy.set_allow_overwrite(self.dir, False)
        library_policy.set_library_version(self.dir, 2)
        self.assertFalse(library_policy.allow_overwrite(self.dir))
        library_policy.set_allow_overwrite(self.dir, True)
        self.assertEqual(2, library_policy.library_version(self.dir))

    def test_anything_but_a_whole_number_reads_as_1(self):
        for value in ("x", "2", 0, -1, 2.5, True, None):
            with self.subTest(value=value):
                with open(self.path, "w", encoding="utf-8") as handle:
                    json.dump({library_policy.VERSION_KEY: value}, handle)
                self.assertEqual(1, library_policy.library_version(self.dir))

    def test_an_unreadable_policy_reads_as_1(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{ not json")
        self.assertEqual(1, library_policy.library_version(self.dir))

    def test_the_library_tab_shows_it(self):
        from amaze.dialogs import prefs_dialog
        prefs = test_support.fixture_prefs(self)
        dialog = prefs_dialog.PrefsDialog(prefs, panel=None)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual("Format: v1", dialog._lbl_library_format.text())
        library_policy.set_library_version(prefs.dir, 2)
        dialog.refresh_library_version()
        self.assertEqual("Format: v2", dialog._lbl_library_format.text())


class NoLibraryMeansNoPolicyFileTest(unittest.TestCase):
    """With no library open, nothing reads or writes a policy.json in the working folder."""

    def setUp(self):
        self.cwd = tempfile.mkdtemp(prefix="amaze_policy_cwd_")
        self.addCleanup(shutil.rmtree, self.cwd, ignore_errors=True)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.cwd)
        with open("policy.json", "w", encoding="utf-8") as handle:
            json.dump({"allow_overwrite": False}, handle)

    def test_no_library_reads_and_writes_nothing_in_the_working_folder(self):
        self.assertEqual(
            library_policy.DEFAULTS, library_policy.read(""),
            "with no library the policy was read from the working folder")
        self.assertTrue(library_policy.allow_overwrite(""))
        before = sorted(os.listdir(self.cwd))
        self.assertFalse(library_policy.set_allow_overwrite("", True))
        self.assertEqual(before, sorted(os.listdir(self.cwd)),
                         "a refused write still left files in the working "
                         "folder")


class OverwriteIsGatedInTheMODELTest(unittest.TestCase):
    """The refusal has to sit where every caller passes: the dialog also stops offering Overwrite, but a UI check is only a suggestion."""

    def test_the_model_and_the_dialog_both_consult_the_policy(self):
        """The model refuses before any file is written; the dialog does not offer the button."""
        import re
        package = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(package, "core", "library.py"),
                  encoding="utf-8") as handle:
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
        with open(os.path.join(package, "panel", "panel.py"),
                  encoding="utf-8") as handle:
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

    def test_every_shape_on_disk_reads_as_it_should(self):
        """Absent and a BOM read as written; every broken shape reads as the strictest."""
        def text(body, encoding="utf-8"):
            def write(path):
                with open(path, "w", encoding=encoding) as handle:
                    handle.write(body)
            return write

        def dangling(path):
            os.symlink(os.path.join(os.path.dirname(path), "not-there.json"),
                       path)

        for why, make, allowed in (
                ("absent, a library older than the policy", lambda _p: None, True),
                ("a BOM a Windows editor leaves", text(json.dumps(
                    {"allow_overwrite": True,
                     "version": library_policy.POLICY_VERSION}), "utf-8-sig"), True),
                ("truncated", text('{"allow_overwrite": true, '), False),
                ("not an object", text('["allow_overwrite"]'), False),
                ('bool("false") is True',
                 text(json.dumps({"allow_overwrite": "false"})), False),
                ("a real false", text(json.dumps({"allow_overwrite": False})), False),
                ("a link to nothing", dangling, False),
                ("a folder in its place", os.mkdir, False)):
            with self.subTest(why):
                folder = tempfile.mkdtemp(prefix="amaze_policy_shape_")
                self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
                make(library_policy.path_for(folder))
                self.assertEqual(allowed, library_policy.allow_overwrite(folder),
                                 "policy.json %s read the wrong way" % why)

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


if __name__ == "__main__":
    unittest.main()
