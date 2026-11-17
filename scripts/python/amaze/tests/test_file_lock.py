"""`hostos.file_lock` - a best-effort exclusive lock that NEVER blocks a write."""

import os
import shutil
import tempfile
import unittest

from amaze.helpers import hostos
from amaze.tests import test_support  # noqa: F401


class _Case(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_file_lock_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "library.json")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{}")


class ItTakesAndReleases(_Case):

    def test_a_second_caller_gets_false_while_the_first_holds_it(self):
        with hostos.file_lock(self.path) as first:
            self.assertTrue(first)
            with hostos.file_lock(self.path) as second:
                self.assertFalse(
                    second,
                    "both callers got True from file_lock, so the lock "
                    "excludes nothing")


class ItNeverPreventsAWrite(_Case):

    def test_an_unlockable_file_yields_false_rather_than_raising(self):
        """A network share may not support locking at all; the write must still happen."""
        real = hostos._take_lock
        hostos._take_lock = lambda handle: (_ for _ in ()).throw(OSError("no"))
        self.addCleanup(setattr, hostos, "_take_lock", real)

        with hostos.file_lock(self.path) as held:
            self.assertFalse(held, "it returned True for a lock it could not take")

    def test_the_library_folder_is_not_touched(self):
        """Three suite checks fail on an extra file there, one of them on a SUCCESSFUL save."""
        before = sorted(os.listdir(self.dir))
        with hostos.file_lock(self.path):
            pass
        self.assertEqual(before, sorted(os.listdir(self.dir)),
                         "the lock left a file in the library folder")

    def test_a_raising_body_still_releases(self):
        with self.assertRaises(ValueError):
            with hostos.file_lock(self.path):
                raise ValueError("boom")
        with hostos.file_lock(self.path) as after:
            self.assertTrue(after, "the lock was held after the body raised")


if __name__ == "__main__":
    unittest.main()
