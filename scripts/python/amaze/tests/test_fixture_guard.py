"""The fixture generator's identity guard, driven against every way an earlier version of it passed something it should have caught. ▸p/guard-must-be-independent"""

import os
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
        self.addCleanup(lambda: None)
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

    def test_the_real_shape(self):
        self.assertLeaks(b"  author builduser@buildbox.local\n")

    def test_a_bare_host_name_with_no_stamp_around_it(self):
        """`iconvert` writes the host into TIFF `HostComputer` as a bare value, so a pattern keyed on `user@host` alone never sees it."""
        self.assertLeaks(b"hostname\x00buildbox.local\x00\n")

    def test_a_two_character_account(self):
        """A length floor is how the first version skipped short names."""
        self.assertLeaks(b"  author ab@buildbox\n", account="ab",
                         host="buildbox")

    def test_an_account_that_prefixes_the_stand_in(self):
        """`amaz` truncated to `amaz` is a redaction that changes nothing, and a prefix test then reads it as already neutral."""
        self.assertLeaks(b"  author amaz@buildbox\n", account="amaz",
                         host="buildbox")

    def test_two_short_names_do_not_build_an_empty_alternation(self):
        """An empty alternation matches at every offset - it once rewrote 24 unrelated spans and reported them as identities."""
        self.assertLeaks(b"author ab@xy.local and some.dotted.text\n",
                         account="ab", host="xy")

    def test_the_per_user_temp_directory(self):
        """macOS per-user temp is an account-specific token, and pointing a scene's JOB and POSE at it swapped one machine-local path for another the guard could not see."""
        self.pin("builduser", "BuildBox")
        path = self.write(b"set -g HIP = '/var/folders/zz/"
                          b"zyxwvuts9876rqpo5432nmlk0000gn/T/x'\n")
        self.assertTrue(gen.complaints(path),
                        "the per-user temp token passed the guard")

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

    def test_a_substring_of_an_ordinary_word(self):
        """Without a word boundary a three-letter account rewrites `timeline` and `optimize`, length-preserving and invisible."""
        self.assertInnocent(b"timeshift optimize timeline chan time\n",
                            account="tim", host="buildbox")

    def test_an_already_redacted_stamp(self):
        self.assertInnocent(b"  author amaze-@amaze----------\n")

    def test_placeholder_home_paths(self):
        self.assertInnocent(b"/Users/someone /Users/someone-else "
                            b"/home/projects\n")

    def test_ordinary_fixture_bytes(self):
        self.assertInnocent(b"cube geometry, nothing personal\n")


class TheStandInKeepsTheLengthAndChangesTheValue(unittest.TestCase):

    def test_the_length_never_moves(self):
        """A shorter stand-in shifts every following byte and Houdini refuses the file outright. ▸r/author-stamp"""
        for size in range(1, 41):
            with self.subTest(size=size):
                value = b"n" * size
                self.assertEqual(size, len(gen.stand_in(value)))

    def test_no_input_survives_as_its_own_stand_in(self):
        """Except the stand-ins themselves, which must be stable so a redacted file is recognised as redacted rather than rewritten again."""
        for value in (b"builduser", b"buildbox.local", b"amaz", b"ab"):
            with self.subTest(value=value):
                replacement = gen.stand_in(value)
                self.assertNotEqual(value, replacement)
                self.assertEqual(replacement, gen.stand_in(replacement))


if __name__ == "__main__":
    unittest.main()
