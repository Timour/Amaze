"""A test skipped on EVERY Houdini protects nothing and reads as coverage.

Pins the intersection in both polarities, the four refusals, the stdlib
guarantee behind them, and the wiring.
(practice.md > A TEST SKIPPED ON EVERY MAJOR IS DEAD COVER)
"""

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
#: Siblings in tests/, run as scripts - resolved the runner's way.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_dead_cover                                   # noqa: E402
import run_suite                                          # noqa: E402
from amaze.tests import test_support                      # noqa: E402,F401

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
RUN_TESTS_SH = os.path.join(REPO, "tools", "run-tests.sh")

H22 = ("/Applications/Houdini/Houdini22.0.403/Frameworks/Houdini.framework"
       "/Versions/Current/Resources")
H21 = ("/Applications/Houdini/Houdini21.0.729/Frameworks/Houdini.framework"
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

    def write_report(self, name, skipped, houdini=H22, tests_run=1784):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"houdini": houdini, "testsRun": tests_run,
                       "ok": True, "skipped": skipped}, handle)
        return path

    def run_check(self, *paths):
        #: The real main(), captured - not a subprocess, so a failure
        #: shows a traceback instead of an exit code to go hunting for.
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = check_dead_cover.main(list(paths))
        return code, out.getvalue() + err.getvalue()


class TheIntersectionTest(_ReportsMixin):

    def test_a_test_skipped_on_every_host_is_named(self):
        a = self.write_report("a.json", [
            ["test_x.A.test_needs_redshift", "Redshift not installed"],
            ["test_y.B.test_dead", "needs a GUI"]], houdini=H22)
        b = self.write_report("b.json", [
            ["test_y.B.test_dead", "needs a GUI"],
            ["test_z.C.test_h22_only", "H22 only"]], houdini=H21)
        code, output = self.run_check(a, b)
        self.assertEqual(code, 1, "a test skipped on both hosts was not "
                                  "reported as dead cover:\n%s" % output)
        self.assertIn("test_y.B.test_dead", output,
                      "the dead test was not NAMED, and a count is exactly "
                      "what the suite already gave us")

    def test_a_test_skipped_on_only_one_host_is_not_named(self):
        a = self.write_report("a.json", [
            ["test_x.A.test_needs_redshift", "Redshift not installed"]],
            houdini=H22)
        b = self.write_report("b.json", [
            ["test_z.C.test_h22_only", "H22 only"]], houdini=H21)
        code, output = self.run_check(a, b)
        self.assertEqual(code, 0, "a skip that is CORRECT on its host was "
                                  "reported as dead cover, and a checker "
                                  "that names everything gets turned off "
                                  "within a day:\n%s" % output)
        self.assertNotIn("test_x.A.test_needs_redshift", output)
        self.assertNotIn("test_z.C.test_h22_only", output)

    def test_the_reason_from_every_host_is_shown(self):
        a = self.write_report("a.json", [
            ["test_y.B.test_dead", "Redshift not installed"]], houdini=H22)
        b = self.write_report("b.json", [
            ["test_y.B.test_dead", "no hou.ui headless"]], houdini=H21)
        code, output = self.run_check(a, b)
        self.assertEqual(code, 1)
        for expected in ("Redshift not installed", "no hou.ui headless",
                         "Houdini22.0.403", "Houdini21.0.729"):
            self.assertIn(expected, output,
                          "each host's own reason and name must show - the "
                          "difference between them IS the diagnosis")


class TheRefusalsTest(_ReportsMixin):

    def test_a_missing_report_refuses(self):
        a = self.write_report("a.json", [])
        code, output = self.run_check(a, os.path.join(self.dir, "gone.json"))
        self.assertEqual(code, 2, "a missing report was treated as a run "
                                  "that skipped nothing:\n%s" % output)
        self.assertIn("crashed", output)

    def test_an_unreadable_report_refuses(self):
        a = self.write_report("a.json", [])
        bad = os.path.join(self.dir, "bad.json")
        with open(bad, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        code, output = self.run_check(a, bad)
        self.assertEqual(code, 2, "unreadable JSON did not refuse:\n%s"
                         % output)
        self.assertIn("unreadable", output)

    def test_a_run_that_executed_nothing_refuses(self):
        a = self.write_report("a.json", [["test_y.B.test_dead", "why"]])
        crashed = self.write_report("crashed.json", [], tests_run=0)
        code, output = self.run_check(a, crashed)
        self.assertEqual(code, 2, "a crashed run intersected to an empty "
                                  "set and produced a confident all-clear "
                                  "from a suite that never ran; a Houdini "
                                  "crash exits 0, so testsRun is the only "
                                  "signal:\n%s" % output)
        self.assertIn("0 tests", output)

    def test_one_report_alone_refuses(self):
        a = self.write_report("a.json", [["test_y.B.test_dead", "why"]])
        code, output = self.run_check(a)
        self.assertEqual(code, 2, "one run cannot tell a correct skip from "
                                  "a dead one, but answered anyway:\n%s"
                         % output)
        self.assertIn("at least", output)


class TheHostNameTest(unittest.TestCase):

    def test_the_version_directory_is_what_gets_reported(self):
        self.assertEqual(
            check_dead_cover.host_of({"houdini": H21}), "Houdini21.0.729")

    def test_an_unnamed_install_still_reads(self):
        self.assertEqual(
            check_dead_cover.host_of({"houdini": ""}), "(newest install)")


class TheReportWriterTest(_ReportsMixin):

    def test_the_report_carries_ids_reasons_and_the_count(self):
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

    def test_the_written_report_is_what_the_checker_reads(self):
        dead = ("test_y.B.test_dead", "dead everywhere")
        for name, houdini in (("a.json", H22), ("b.json", H21)):
            os.environ["AMAZE_HOUDINI"] = houdini
            self.addCleanup(os.environ.pop, "AMAZE_HOUDINI", None)
            run_suite.write_skip_report(
                _FakeResult([dead], tests_run=1784),
                os.path.join(self.dir, name))
        code, output = self.run_check(os.path.join(self.dir, "a.json"),
                                      os.path.join(self.dir, "b.json"))
        self.assertEqual(code, 1, "the writer's own output did not reach "
                                  "the checker, so the two halves are "
                                  "pinned only against a hand-built "
                                  "fixture:\n%s" % output)
        self.assertIn("test_y.B.test_dead", output)
        self.assertIn("Houdini21.0.729", output)

    def test_the_env_var_name_is_the_one_the_shell_sets(self):
        self.assertEqual(run_suite.SKIP_REPORT_VAR, "AMAZE_SKIP_REPORT")


class WhatUnittestItselfGuaranteesTest(unittest.TestCase):

    def test_a_result_carries_skipped_ids_not_just_a_count(self):
        class Sample(unittest.TestCase):
            @unittest.skip("decorator")
            def test_decorator(self):
                raise AssertionError("must not run")

            @unittest.skipIf(True, "conditional")
            def test_conditional(self):
                raise AssertionError("must not run")

            def test_runtime(self):
                self.skipTest("runtime")

        suite = unittest.TestLoader().loadTestsFromTestCase(Sample)
        result = unittest.TextTestRunner(
            stream=io.StringIO(), verbosity=0).run(suite)
        ids = {test.id().rsplit(".", 1)[-1] for test, _ in result.skipped}
        self.assertEqual(ids, {"test_decorator", "test_conditional",
                               "test_runtime"},
                         "unittest no longer reports every skip KIND with "
                         "an id, and check_dead_cover cannot work without "
                         "it")
        self.assertTrue(all(reason for _, reason in result.skipped),
                        "a skip reason came back empty, so the check would "
                        "name a dead test with nothing to act on")


class TheWiringTest(unittest.TestCase):

    def setUp(self):
        with open(RUN_TESTS_SH, encoding="utf-8") as handle:
            self.source = handle.read()

    def test_all_versions_hands_each_run_its_own_report(self):
        self.assertIn('AMAZE_SKIP_REPORT="$report"', self.source,
                      "--all-versions no longer gives each run a skip "
                      "report, so the checker has nothing to compare")

    def test_all_versions_runs_the_checker(self):
        self.assertIn("check_dead_cover.py", self.source,
                      "--all-versions no longer runs the dead-cover check, "
                      "and a checker nobody calls is the same false green "
                      "as a dead test")

    def test_a_subset_run_does_not_answer_the_question(self):
        self.assertIn("full_run", self.source,
                      "the subset guard is gone, so a subset --all-versions "
                      "would report a confident all-clear about every "
                      "module neither run loaded")


if __name__ == "__main__":
    unittest.main()
