"""`check_dead_cover.py`: tests skipped on every Houdini, and its exit 2 on bad input."""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_dead_cover
import run_suite
from amaze.tests import test_support                      # noqa: F401

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

H22_0 = ("/Applications/Houdini/Houdini22.0/Frameworks/Houdini.framework"
         "/Versions/Current/Resources")
H22_5 = ("/Applications/Houdini/Houdini22.5/Frameworks/Houdini.framework"
         "/Versions/Current/Resources")


class _FakeTest:

    def __init__(self, test_id):
        self._id = test_id

    def id(self):
        return self._id


class _FakeResult:

    def __init__(self, skipped, tests_run=10, ok=True):
        self.skipped = [(_FakeTest(i), reason) for i, reason in skipped]
        self.testsRun = tests_run
        self._ok = ok

    def wasSuccessful(self):
        return self._ok


class _ReportsMixin(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_deadcover_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def write_report(self, name, skipped, houdini=H22_0, tests_run=1784):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"houdini": houdini, "testsRun": tests_run,
                       "ok": True, "skipped": skipped}, handle)
        return path

    def run_check(self, *paths):
        #: The real main(), captured - a subprocess gives an exit code, not a traceback.
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = check_dead_cover.main(list(paths))
        return code, out.getvalue() + err.getvalue()


class TheIntersectionTest(_ReportsMixin):

    def test_gt63_a_test_skipped_on_only_one_host_is_not_named(self):
        a = self.write_report("a.json", [
            ["test_x.A.test_needs_redshift", "Redshift not installed"]],
            houdini=H22_0)
        b = self.write_report("b.json", [
            ["test_z.C.test_h22_only", "H22 only"]], houdini=H22_5)
        code, output = self.run_check(a, b)
        self.assertEqual(code, 0, "a skip that is CORRECT on its host was "
                                  "reported as dead cover, and a checker "
                                  "that names everything gets turned off "
                                  "within a day:\n%s" % output)
        self.assertNotIn("test_x.A.test_needs_redshift", output)
        self.assertNotIn("test_z.C.test_h22_only", output)

    def test_gt64_the_reason_from_every_host_is_shown(self):
        a = self.write_report("a.json", [
            ["test_y.B.test_dead", "Redshift not installed"]], houdini=H22_0)
        b = self.write_report("b.json", [
            ["test_y.B.test_dead", "no hou.ui headless"]], houdini=H22_5)
        code, output = self.run_check(a, b)
        self.assertEqual(code, 1)
        self.assertIn("test_y.B.test_dead", output,
                      "the dead test's id is not in the output, and a count "
                      "alone is what the suite already prints")
        for expected in ("Redshift not installed", "no hou.ui headless",
                         "Houdini22.0", "Houdini22.5"):
            self.assertIn(expected, output,
                          "each host's own reason and name must show - the "
                          "difference between them IS the diagnosis")


class TheExitCodeTwoTest(_ReportsMixin):

    def test_gt65_every_unusable_report_exits_with_2(self):
        """Exit 2, never 0: a Houdini crash exits 0, so testsRun is the only signal."""
        a = self.write_report("a.json", [["test_y.B.test_dead", "why"]])
        bad = os.path.join(self.dir, "bad.json")
        with open(bad, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        crashed = self.write_report("crashed.json", [], tests_run=0)
        for why, paths, said in (
                ("a missing report", (a, os.path.join(self.dir, "gone.json")),
                 "crashed"),
                ("unreadable JSON", (a, bad), "unreadable"),
                ("a run that executed nothing", (a, crashed), "0 tests"),
                ("one report alone", (a,), "at least")):
            with self.subTest(why):
                code, output = self.run_check(*paths)
                self.assertEqual(code, 2, "%s did not exit with 2:\n%s"
                                 % (why, output))
                self.assertIn(said, output)


class TheHostNameTest(unittest.TestCase):

    def test_gt66_the_version_directory_is_what_gets_reported(self):
        self.assertEqual(
            check_dead_cover.host_of({"houdini": H22_5}), "Houdini22.5")
        self.assertEqual(
            check_dead_cover.host_of({"houdini": ""}), "(production build)")


class TheReportWriterTest(_ReportsMixin):

    def test_gt67_the_report_holds_ids_reasons_and_the_count(self):
        result = _FakeResult([("test_b.B.test_two", "second"),
                              ("test_a.A.test_one", "first")], tests_run=42)
        path = os.path.join(self.dir, "report.json")
        run_suite.write_skip_report(result, path)
        with open(path, encoding="utf-8") as handle:
            report = json.load(handle)
        self.assertEqual(report["testsRun"], 42)
        self.assertEqual([entry[0] for entry in report["skipped"]],
                         ["test_a.A.test_one", "test_b.B.test_two"],
                         "the skip list is not sorted, so two runs would "
                         "differ on ORDER alone")
        self.assertEqual(dict(report["skipped"])["test_a.A.test_one"],
                         "first")

    def test_gt68_the_written_report_is_what_the_checker_reads(self):
        dead = ("test_y.B.test_dead", "dead everywhere")
        for name, houdini in (("a.json", H22_0), ("b.json", H22_5)):
            run_suite.write_skip_report(
                _FakeResult([dead], tests_run=1784),
                os.path.join(self.dir, name), houdini)
        code, output = self.run_check(os.path.join(self.dir, "a.json"),
                                      os.path.join(self.dir, "b.json"))
        self.assertEqual(code, 1, "check_dead_cover.main did not find the "
                                  "dead test in reports written by "
                                  "write_skip_report, so the two only match "
                                  "a hand-built fixture:\n%s" % output)
        self.assertIn("test_y.B.test_dead", output)
        self.assertIn("Houdini22.5", output)


if __name__ == "__main__":
    unittest.main()
