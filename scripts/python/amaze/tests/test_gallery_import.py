"""Gallery Import saves each entry through the save its caller hands in. ▸r/gallery-entries"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

import hou  # noqa: E402,F401

from amaze.core import gallery_import  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401 - redirects the log


class EachEntryGoesThroughTheSaveHandedIn(unittest.TestCase):
    """The caller's `save` takes every entry; a refused save counts as failed, never imported."""

    def test_two_entries_one_refused(self):
        node = mock.Mock()
        entry = mock.Mock()
        entry.canCreateChildNode.return_value = True
        entry.createChildNode.return_value = node
        entry.name.return_value = "probe"
        saved = []
        answers = iter(["Karma", ""])
        summary = gallery_import.import_entries(
            lambda *args: saved.append(args) or next(answers),
            [(entry, "mtlxstandard_surface", "Metal"),
             (entry, "mtlxstandard_surface", "Wood")])
        self.assertEqual([(node, "Metal", "gallery", False),
                          (node, "Wood", "gallery", False)], saved)
        self.assertEqual((1, 1), (summary["imported"], summary["failed"]))


if __name__ == "__main__":
    unittest.main()
