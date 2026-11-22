"""Check Library, run on a private copy of the real library."""

import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from amaze.core import library_files, material, repair  # noqa: E402
from amaze.tests import test_support                      # noqa: E402


class TheRealLibrarysEveryFolderTest(unittest.TestCase):
    """Every folder of the real library: databases and records in full, the rest placeholders."""

    def setUp(self):
        live = test_support.live_library_to_rehearse_on(self)
        self.dir = tempfile.mkdtemp(prefix="amaze_check_real_") + os.sep
        self.addCleanup(shutil.rmtree, self.dir, True)
        source_root = os.path.normpath(live.dir)
        self.files = 0
        for folder, dirs, names in os.walk(source_root):
            relative = os.path.relpath(folder, source_root)
            here = os.path.normpath(os.path.join(self.dir, relative))
            os.makedirs(here, exist_ok=True)
            if relative in (library_files.PACKAGE_FOLDER, library_files.TRASH_FOLDER):
                dirs[:] = []    # a permanent folder the check never scans
                continue
            for name in names:
                source = os.path.join(folder, name)
                target = os.path.join(here, name)
                if relative == "." or name.endswith((material.RECORD_SUFFIX, ".interface")):
                    shutil.copy2(source, target)    # copied whole, as they are read
                else:
                    with open(target, "wb") as handle:
                        handle.write(b"x")
                    stat = os.stat(source)
                    os.utime(target, (stat.st_atime, stat.st_mtime))
                self.files += 1
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)

    def test_unlisted_files_leftovers_and_unknowns_are_told_apart(self):
        test_support.reset_database_singletons()
        started = time.perf_counter()
        findings = repair.survey(self.dir, "img/")
        took = time.perf_counter() - started
        sys.stderr.write("\n  Check Library's survey of the real library's shape: "
                         "%.0f ms over %d files\n" % (took * 1000, self.files))
        self.assertTrue(findings["complete"])
        self.assertEqual(0, repair.unaccounted_total(findings),
                         "files no section lists: %r" % {
                             folder: names[:5]
                             for folder, names in findings["unaccounted"].items()})
        leftovers = {entry[0] for entry in findings["leftovers"]}
        unknown = ({entry[0] for entry in findings["unknown"]}
                   | {entry[0] for entry in findings["unknown_folders"]})
        self.assertEqual(set(), leftovers & unknown,
                         "one file was listed both as a leftover and as unknown")
        text = "\n".join(repair.report_lines(findings))
        self.assertNotIn("img/comments", text, "the comment pictures folder is reported")


if __name__ == "__main__":
    unittest.main()
