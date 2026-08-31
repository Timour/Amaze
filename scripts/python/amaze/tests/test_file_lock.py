"""`hostos.file_lock` - a best-effort exclusive lock that NEVER costs a write."""

import os
import shutil
import tempfile
import unittest

from amaze.helpers import hostos


class _Case(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_file_lock_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "library.json")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{}")


class ItTakesAndReleases(_Case):

    def test_it_reports_the_lock_it_took(self):
        with hostos.file_lock(self.path) as held:
            self.assertTrue(held, "the lock was not taken on a plain local file")

    def test_a_second_caller_is_refused_while_the_first_holds_it(self):
        with hostos.file_lock(self.path) as first:
            self.assertTrue(first)
            with hostos.file_lock(self.path) as second:
                self.assertFalse(
                    second,
                    "two callers both believed they held it, so the lock "
                    "narrows nothing")

    def test_a_second_caller_gets_it_after_the_first_lets_go(self):
        with hostos.file_lock(self.path) as first:
            self.assertTrue(first)
        with hostos.file_lock(self.path) as second:
            self.assertTrue(second, "the lock was never released")

    def test_it_does_not_leave_the_lock_file_open(self):
        for _ in range(40):    # a leaked descriptor per save runs a session out of them
            with hostos.file_lock(self.path):
                pass


class ItNeverCostsAWrite(_Case):

    def test_an_unlockable_file_yields_false_rather_than_raising(self):
        """A network share may refuse locking outright; the write must still go."""
        real = hostos._take_lock
        hostos._take_lock = lambda handle: (_ for _ in ()).throw(OSError("no"))
        self.addCleanup(setattr, hostos, "_take_lock", real)

        with hostos.file_lock(self.path) as held:
            self.assertFalse(held, "it claimed a lock it could not take")

    def test_the_library_folder_is_not_touched(self):
        """Three suite guards refuse a stray in there, and one of them is a SUCCESSFUL save."""
        before = sorted(os.listdir(self.dir))
        with hostos.file_lock(self.path):
            pass
        self.assertEqual(before, sorted(os.listdir(self.dir)),
                         "the lock left a file beside the library")

    def test_the_body_still_runs_when_the_lock_is_refused(self):
        real = hostos._take_lock
        hostos._take_lock = lambda handle: (_ for _ in ()).throw(OSError("no"))
        self.addCleanup(setattr, hostos, "_take_lock", real)

        ran = []
        with hostos.file_lock(self.path):
            ran.append(True)
        self.assertEqual([True], ran, "a refused lock skipped the write")

    def test_a_raising_body_still_releases(self):
        with self.assertRaises(ValueError):
            with hostos.file_lock(self.path):
                raise ValueError("boom")
        with hostos.file_lock(self.path) as after:
            self.assertTrue(after, "the lock was held after the body raised")


if __name__ == "__main__":
    unittest.main()
