"""`hostos.peer_read` - the ONE freshness check every merge path uses."""

import json
import os
import shutil
import tempfile
import unittest

from amaze.helpers import hostos


class PeerReadTest(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_peer_read_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, "table.json")

    def _write(self, payload, raw=None):
        with open(self.path, "wb") as handle:
            handle.write(raw if raw is not None
                         else json.dumps(payload).encode("utf-8"))

    def _read(self, baseline=None):
        return hostos.peer_read(self.path, baseline)

    def test_an_absent_file_is_absent_not_unreadable(self):
        answer = self._read()
        self.assertEqual(hostos.PEER_ABSENT, answer.verdict)
        self.assertIsNone(answer.document)
        self.assertIsNone(answer.fingerprint)

    def test_a_first_read_reports_the_document_and_a_fingerprint(self):
        self._write({"a": 1})
        answer = self._read()
        self.assertEqual(hostos.PEER_CHANGED, answer.verdict)
        self.assertEqual({"a": 1}, answer.document)
        self.assertTrue(answer.fingerprint)

    def test_the_same_bytes_read_twice_are_unchanged(self):
        self._write({"a": 1})
        first = self._read()
        again = self._read(first.fingerprint)
        self.assertEqual(hostos.PEER_UNCHANGED, again.verdict)
        self.assertIsNone(again.document)
        self.assertEqual(first.fingerprint, again.fingerprint)

    def test_a_rewrite_of_identical_bytes_is_unchanged(self):
        """A save that writes what was already there is not a peer edit."""
        self._write({"a": 1})
        first = self._read()
        self._write({"a": 1})
        self.assertEqual(hostos.PEER_UNCHANGED, self._read(first.fingerprint).verdict)

    def test_a_same_size_edit_is_caught(self):
        """Same byte count, different content - and NOT a discriminator here, since APFS moves the mtime so a stat passes it too; the identical-bytes case above is the one that separates them. ▸r/peer-read"""
        self._write({"a": 1})
        first = self._read()
        self._write({"a": 2})
        answer = self._read(first.fingerprint)
        self.assertEqual(hostos.PEER_CHANGED, answer.verdict,
                         "a same-size peer edit read as unchanged")
        self.assertEqual({"a": 2}, answer.document)

    def test_an_unparseable_file_refuses_rather_than_reporting_nothing(self):
        self._write(None, raw=b"{ this is not json")
        answer = self._read()
        self.assertEqual(hostos.PEER_UNREADABLE, answer.verdict,
                         "a caller told 'nothing changed' would write over it")
        self.assertIsNone(answer.document)

    def test_a_bom_is_read_not_refused(self):
        self._write(None, raw=b"\xef\xbb\xbf" + json.dumps({"a": 1}).encode())
        answer = self._read()
        self.assertEqual(hostos.PEER_CHANGED, answer.verdict)
        self.assertEqual({"a": 1}, answer.document)

    def test_a_document_that_is_not_a_dict_is_unreadable(self):
        self._write([1, 2, 3])
        self.assertEqual(hostos.PEER_UNREADABLE, self._read().verdict)

    def test_unreadable_carries_the_reason_for_the_debug_log(self):
        self._write(None, raw=b"{ this is not json")
        self.assertTrue(self._read().error,
                        "the refusal names no cause, so the log cannot either")

    def test_fingerprint_of_matches_peer_read_without_parsing(self):
        """The identity door for a caller that does not want the document."""
        self._write({"a": 1})
        self.assertEqual(self._read().fingerprint,
                         hostos.fingerprint_of(self.path))

    def test_fingerprint_of_an_unparseable_file_still_answers(self):
        """A save compares identities; whether it PARSES is a later question."""
        self._write(None, raw=b"{ this is not json")
        self.assertTrue(hostos.fingerprint_of(self.path))

    def test_fingerprint_of_an_absent_file_is_none(self):
        self.assertIsNone(hostos.fingerprint_of(self.path))

    def test_a_file_that_vanished_since_the_baseline_reads_absent(self):
        self._write({"a": 1})
        first = self._read()
        os.remove(self.path)
        answer = self._read(first.fingerprint)
        self.assertEqual(hostos.PEER_ABSENT, answer.verdict)


if __name__ == "__main__":
    unittest.main()
