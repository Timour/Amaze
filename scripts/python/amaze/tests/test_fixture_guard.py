"""The fixture generator's identity guard, driven against every way an earlier version of it passed something it should have caught. ▸p/guard-must-be-independent"""

import os
import shutil
import sys
import tempfile
import unittest

import hou  # noqa: F401 - the module under test imports it

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.tests import make_file_fixtures as gen  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401 - redirects the log


class GuardCase(unittest.TestCase):

    def pin(self, account, host):
        """Answer as a machine with this account and host name."""
        real = gen.real_account
        self.addCleanup(setattr, gen, "real_account", real)
        gen.real_account = lambda: account
        stub = type("_S", (), {"gethostname": staticmethod(lambda: host)})()
        real_socket = gen.socket
        self.addCleanup(setattr, gen, "socket", real_socket)
        gen.socket = stub

    def write(self, payload, suffix=".bgeo"):
        folder = tempfile.mkdtemp(prefix="amaze_guard_")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        path = os.path.join(folder, "probe" + suffix)
        with open(path, "wb") as handle:
            handle.write(payload)
        return path

    def assertLeaks(self, payload, account="builduser", host="BuildBox"):
        """Detected before redaction, and gone after it."""
        self.pin(account, host)
        path = self.write(payload)
        self.assertTrue(
            gen.complaints(path),
            "the guard passed a payload carrying %s@%s: %r"
            % (account, host, payload))
        gen.redact_identity(path)
        self.assertEqual(
            [], gen.complaints(path),
            "redaction did not clean %r" % payload)

    def assertInnocent(self, payload, account="builduser", host="BuildBox"):
        """Left alone, and reported clean."""
        self.pin(account, host)
        path = self.write(payload)
        self.assertEqual(
            0, gen.redact_identity(path),
            "the redactor rewrote bytes it had no business in: %r" % payload)
        self.assertEqual([], gen.complaints(path),
                         "the guard flagged innocent bytes: %r" % payload)


class TheGuardCatchesWhatEarlierVersionsPassed(GuardCase):

    def test_every_shape_an_earlier_version_passed_is_caught(self):
        """Each row once passed the guard; each is now caught, then redacted clean."""
        for why, payload, account, host in (
                ("the real shape", b"  author builduser@buildbox.local\n",
                 "builduser", "BuildBox"),
                ("iconvert's bare TIFF HostComputer",
                 b"hostname\x00buildbox.local\x00\n", "builduser", "BuildBox"),
                ("a length floor skipped short names",
                 b"  author ab@buildbox\n", "ab", "buildbox"),
                ("an account prefixing the stand-in",
                 b"  author amaz@buildbox\n", "amaz", "buildbox"),
                ("an empty alternation matched everywhere",
                 b"author ab@xy.local and some.dotted.text\n", "ab", "xy")):
            with self.subTest(why):
                self.assertLeaks(payload, account=account, host=host)

    def test_a_machine_local_path_is_a_finding(self):
        """A per-user temp folder and a Windows home, slashed either way. ▸r/launching-shell-decides"""
        self.pin("builduser", "BuildBox")
        for payload in (b"set -g HIP = '/var/folders/zz/"    # invented, as a lifted token is a leak
                        b"zyxw9vut8srq7pon6mlk0000gn/T/x'\n",
                        b"set -g HIP = 'C:/Users/somebody/houdini22.0/x'\n",
                        b"c:\\users\\somebody\\Documents\\x\n"):
            with self.subTest(payload=payload):
                self.assertTrue(
                    gen.complaints(self.write(payload)),
                    "a machine-local path passed the guard: %r" % payload)

    def test_an_opaque_format_is_a_finding_not_a_pass(self):
        """A byte scan cannot see inside a compressed payload, so silence there is unproven rather than clean."""
        self.pin("builduser", "BuildBox")
        path = self.write(b"scf1" + b"\0" * 40, suffix=".bgeo.sc")
        found = gen.complaints(path)
        self.assertTrue(any("OPAQUE" in text for text in found),
                        "an unreadable payload was reported clean: %s" % found)

    def test_every_cleared_file_names_its_evidence(self):
        """Clearing an opaque format is allowed, but only against a recorded measurement."""
        self.assertTrue(gen.CLEARED, "nothing is cleared, so the exemption "
                                     "path is never exercised")
        for name, evidence in gen.CLEARED.items():
            with self.subTest(fixture=name):
                self.assertRegex(
                    evidence, r"20\d\d-\d\d-\d\d",
                    "%s is cleared without a dated measurement" % name)


class TheGuardDoesNotCryWolf(GuardCase):

    def test_innocent_bytes_are_left_alone(self):
        """A short account inside a word, a redacted stamp, and placeholder home paths."""
        for payload, account, host in (
                (b"timeshift optimize timeline chan time\n", "tim", "buildbox"),
                (b"  author amaze-@amaze----------\n", "builduser", "BuildBox"),
                (b"/Users/someone /Users/someone-else /home/projects\n",
                 "builduser", "BuildBox")):
            with self.subTest(payload=payload):
                self.assertInnocent(payload, account=account, host=host)


class TheStandInKeepsTheLengthAndChangesTheValue(unittest.TestCase):

    def test_the_length_never_moves_and_a_stand_in_is_stable(self):
        """Same length, or Houdini refuses the file; a stand-in maps to itself. ▸r/author-stamp"""
        for size in range(1, 41):
            with self.subTest(size=size):
                value = b"n" * size
                self.assertEqual(size, len(gen.stand_in(value)))
        for value in (b"builduser", b"buildbox.local", b"amaz", b"ab"):
            with self.subTest(value=value):
                replacement = gen.stand_in(value)
                self.assertNotEqual(value, replacement)
                self.assertEqual(replacement, gen.stand_in(replacement))


class SuiteDebrisLandsInTheDesignatedFolder(unittest.TestCase):
    """The Test Library preference EXISTS so test libraries have one home (settled 2026-08-23) - a machine that designates one gets every suite directory under `<test_dir>/suite/`, visible and deletable, never scattered."""

    def test_the_fixture_library_lands_under_the_test_folder(self):
        from amaze.helpers import hostos
        if not test_support.SUITE_ROOT:
            self.skipTest("this machine designates no Test Library "
                          "folder, so tempfile decides")
        path = test_support.fresh_library(self)
        root = hostos.canonical_path_key(test_support.SUITE_ROOT)
        self.assertTrue(
            hostos.canonical_path_key(path).startswith(root),
            "a fixture library landed outside the designated test "
            "folder: %s" % path)

    def test_every_support_scratch_comes_from_the_one_maker(self):
        """A second bare `mkdtemp` in test_support is the leak coming back - every directory it mints goes through `scratch_dir`."""
        import inspect
        body = inspect.getsource(test_support)
        calls = body.count("tempfile.mkdtemp(")
        self.assertEqual(
            1, calls,
            "test_support calls tempfile.mkdtemp %d times - only "
            "scratch_dir may, so the suite root cannot be bypassed"
            % calls)


if __name__ == "__main__":
    unittest.main()
