"""`hostos.peer_read` - the ONE freshness check every merge path uses."""

import json
import os
import shutil
import tempfile
import unittest

from amaze.helpers import hostos
from amaze.tests import test_support  # noqa: F401


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
        for raw in (json.dumps({"a": 1}).encode("utf-8"),
                    b"\xef\xbb\xbf" + json.dumps({"a": 1}).encode("utf-8")):
            with self.subTest(bom=raw.startswith(b"\xef")):
                self._write(None, raw=raw)
                answer = self._read()
                self.assertEqual(hostos.PEER_CHANGED, answer.verdict)
                self.assertEqual({"a": 1}, answer.document)
                self.assertTrue(answer.fingerprint)

    def test_a_rewrite_of_identical_bytes_is_unchanged(self):
        """A save that writes what was already there is not a peer edit."""
        self._write({"a": 1})
        first = self._read()
        self._write({"a": 1})
        again = self._read(first.fingerprint)
        self.assertEqual(hostos.PEER_UNCHANGED, again.verdict)
        self.assertIsNone(again.document)
        self.assertEqual(first.fingerprint, again.fingerprint)

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
        for raw in (b"{ this is not json", json.dumps([1, 2, 3]).encode("utf-8")):
            with self.subTest(raw=raw):
                self._write(None, raw=raw)
                answer = self._read()
                self.assertEqual(hostos.PEER_UNREADABLE, answer.verdict,
                                 "a caller told 'nothing changed' would write over it")
                self.assertIsNone(answer.document)
                self.assertTrue(answer.error,
                                "the refusal names no cause, so the log cannot either")

    def test_fingerprint_of_matches_peer_read_without_parsing(self):
        """The identity door for a caller that does not want the document."""
        for raw in (json.dumps({"a": 1}).encode("utf-8"), b"{ this is not json"):
            with self.subTest(raw=raw):
                self._write(None, raw=raw)
                self.assertEqual(self._read().fingerprint,
                                 hostos.fingerprint_of(self.path))
        os.remove(self.path)
        self.assertIsNone(hostos.fingerprint_of(self.path))


if __name__ == "__main__":
    unittest.main()
