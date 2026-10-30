"""A full run maps what each test runs, per def; a change picks the tests that ran it."""

import importlib.util
import inspect
import json
import linecache
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import impact_map
from amaze.tests import test_support                      # noqa: F401

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
_spec = importlib.util.spec_from_file_location(
    "select_tests", os.path.join(REPO, "tools", "select-tests.py"))
select_tests = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(select_tests)

CODE = "scripts/python/amaze/core/"
TEST_B = "scripts/python/amaze/tests/test_b.py"
SUITE = ["test_a", "test_b", "test_c", "test_d", "test_e", "test_shell_gates", "test_dead_cover"]
ONE = '''"""One."""
LIMIT = 3


def first():
    return LIMIT


def second():
    \x23 a comment
    return 2
'''
TWO = '''"""Two."""
from amaze.core import one


def reads_limit():
    return one.LIMIT + 1


def plain():
    return 0
'''
B = '''def helper():
    return 1


class BTest:
    def test_it(self):
        return helper()

    def test_other(self):
        return 2
'''
IT = "test_b.BTest.test_it"


class TheShapeHashesCodeNotText(unittest.TestCase):

    def test_comments_and_docstrings_move_no_hash(self):
        edited = ONE.replace('"""One."""', '"""One, reworded."""').replace(
            "# a comment", "# another comment\n\n")
        self.assertEqual(impact_map.Code(ONE).shape(), impact_map.Code(edited).shape())

    def test_each_edit_moves_only_its_own_hash(self):
        before = impact_map.Code(ONE + "\n\ndef outer():\n    def inner():\n        return 1\n"
                                       "    return inner\n").shape()
        for why, old, new, part, key in (
                ("a def's body", "return 2", "return 22", "defs", "second"),
                ("a constant", "LIMIT = 3", "LIMIT = 4", "names", "LIMIT"),
                ("an inner def", "return 1\n", "return 11\n", "defs", "outer.<locals>.inner"),
                ("an import", '"""One."""', '"""One."""\nimport os', "imports", "os"),
                ("a call on import", "LIMIT = 3", "LIMIT = 3\nprint(LIMIT)", "effects", None)):
            with self.subTest(why):
                after = impact_map.Code(
                    (ONE + "\n\ndef outer():\n    def inner():\n        return 1\n"
                     "    return inner\n").replace(old, new, 1)).shape()
                moved = sorted((p, k) for p in ("defs", "names", "imports")
                               for k in set(before[p]) | set(after[p])
                               if before[p].get(k) != after[p].get(k))
                if before["effects"] != after["effects"]:
                    moved.append(("effects", None))
                self.assertEqual([(part, key)], moved)

    def test_a_lambda_runs_inside_its_def(self):
        self.assertEqual("outer.<locals>.inner",
                         impact_map.def_name("outer.<locals>.inner.<locals>.<lambda>"))
        self.assertEqual("", impact_map.def_name("<module>"))


class AChangePicksTheTestsThatRanIt(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="amaze_select_")
        self.addCleanup(shutil.rmtree, self.root, True)
        for path, text in ((CODE + "one.py", ONE), (CODE + "two.py", TWO), (TEST_B, B),
                           ("docs/guide.md", "Guide\n"), ("ui/plain.svg", "<svg/>\n")):
            self.write(path, text)
        self.recorder = impact_map.Recorder(self.root)
        self.recorder.tests = [
            "test_a.A.test_1", "test_a.A.test_2", IT, "test_b.BTest.test_other",
            "test_c.C.test_1", "test_d.D.test_1", "test_e.E.test_1",
            "test_shell_gates.G.test_1", "test_dead_cover.H.test_1"]
        self.recorder.ran = {
            "test_a.A.test_1": {CODE + "one.py": {"first"}},
            IT: {CODE + "one.py": {"second"}, CODE + "two.py": {"reads_limit"},
                 TEST_B: {"BTest.test_it", "helper"}},
            "test_b.BTest.test_other": {TEST_B: {"BTest.test_other"}},
            "test_c.C.test_1": {CODE + "two.py": {"plain"}},
            "test_e.E.test_1": {TEST_B: {"helper"}}}
        self.recorder.opened = {"test_a.A.test_2": {"docs/guide.md"},
                                "test_d.D.test_1": {CODE + "one.py"}}
        self.recorder.listed = {"test_c.C.test_1": {"ui"}}

    def write(self, path, text):
        full = os.path.join(self.root, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as handle:
            handle.write(text)

    def pick(self, *changed):
        files = impact_map.snapshot(self.root, [CODE + "one.py", CODE + "two.py", TEST_B,
                                                "docs/guide.md", "ui/plain.svg"])
        self.map = self.recorder.build(files, 1)
        return lambda: select_tests.select(list(changed), self.map, SUITE,
                                           select_tests.reader(self.root))

    def edit(self, path, old, new):
        with open(os.path.join(self.root, path), encoding="utf-8") as handle:
            text = handle.read()
        self.write(path, text.replace(old, new, 1))

    def test_a_def_picks_the_tests_that_ran_it_and_those_that_read_its_file(self):
        picks = self.pick(CODE + "one.py")
        self.edit(CODE + "one.py", "return 2", "return 22")
        self.assertEqual([IT, "test_d"], picks(), "a module all of whose tests are picked "
                                                  "is named whole")

    def test_a_comment_picks_only_the_tests_that_read_the_file(self):
        picks = self.pick(CODE + "one.py")
        self.edit(CODE + "one.py", "# a comment", "# a longer comment")
        self.assertEqual(["test_d"], picks())

    def test_a_constant_picks_every_def_that_uses_it_in_any_file(self):
        picks = self.pick(CODE + "one.py")
        self.edit(CODE + "one.py", "LIMIT = 3", "LIMIT = 4")
        self.assertEqual(["test_a.A.test_1", IT, "test_d"], picks())

    def test_an_import_picks_only_its_own_files_users(self):
        picks = self.pick(CODE + "two.py")
        self.edit(CODE + "two.py", "from amaze.core import one", "import amaze.core.one as one")
        self.assertEqual([IT], picks())

    def test_a_test_module_picks_the_tests_that_run_the_changed_code(self):
        for why, old, new, picked in (
                ("a helper", "return 1", "return 2", [IT, "test_e"]),
                ("a test", "return 2", "return 3", ["test_b.BTest.test_other"]),
                ("a new test", "    def test_other", "    def test_new(self):\n        "
                 "return 4\n\n    def test_other", ["test_b"])):
            with self.subTest(why):
                picks = self.pick(TEST_B)
                self.edit(TEST_B, old, new)
                self.assertEqual(picked, picks())
                self.write(TEST_B, B)

    def test_a_def_run_while_loading_picks_the_users_of_what_it_built(self):
        three = CODE + "three.py"
        self.write(three, "def make():\n    return [1]\n\n\nTABLE = make()\nprint(make())\n\n\n"
                          "def reads_table():\n    return TABLE\n")
        self.recorder.ran[impact_map.LOADING] = {three: {"make"}}
        self.recorder.ran["test_c.C.test_1"][three] = {"reads_table"}
        for why, line, picked in (("a constant it built", 5, ["test_c"]),
                                  ("a call made on import", 6, None)):
            with self.subTest(why):
                self.recorder.anchors = {(three, "make"): {(three, line)}}
                files = impact_map.snapshot(self.root, [CODE + "one.py", CODE + "two.py", TEST_B,
                                                        three, "docs/guide.md", "ui/plain.svg"])
                self.map = self.recorder.build(files, 1)
                self.edit(three, "return [1]", "return [2]")
                self.assertEqual(picked, select_tests.select([three], self.map, SUITE,
                                                             select_tests.reader(self.root)))
                self.edit(three, "return [2]", "return [1]")

    def test_a_test_costs_its_own_seconds_and_its_fixtures(self):
        impact = {"seconds": {"test_b": 1.0, "test_b.BTest": 2.0, IT: 3.0,
                              "test_b.BTest.test_other": 4.0}}
        self.assertEqual(6.0, select_tests.cost([IT], impact))
        self.assertEqual(10.0, select_tests.cost(["test_b"], impact))

    def test_files_pick_their_readers_and_a_new_file_its_folders_listers(self):
        for path, picked in (("docs/guide.md", ["test_a.A.test_2"]), ("docs/other.md", []),
                             ("ui/new.svg", ["test_c"]), ("tools/run-tests.sh",
                                                         ["test_shell_gates", "test_dead_cover"])):
            with self.subTest(path):
                picks = self.pick(path)
                self.write(path, "changed\n")
                self.assertEqual(picked, picks())

    def test_only_the_whole_suite_answers_what_the_map_cannot(self):
        self.recorder.ran[impact_map.LOADING] = {CODE + "two.py": {"plain"}}
        for why, path, old, new in (
                ("a def that runs on import", CODE + "two.py", "return 0", "return 1"),
                ("a module-level call", CODE + "one.py", "LIMIT = 3", "LIMIT = 3\nprint(1)"),
                ("a file no test reads", "ui/plain.svg", "<svg/>", "<svg></svg>"),
                ("code that does not parse", CODE + "one.py", "return 2", "return (")):
            with self.subTest(why):
                picks = self.pick(path)
                self.edit(path, old, new)
                self.assertIsNone(picks())
                self.write(path, {CODE + "one.py": ONE, CODE + "two.py": TWO}.get(path, "<svg/>\n"))
        for path in (CODE + "three.py", "scripts/python/amaze/tests/run_suite.py"):
            with self.subTest(path):
                picks = self.pick(path)
                self.write(path, "x = 1\n")
                self.assertIsNone(picks())
        self.assertIsNone(select_tests.select([CODE + "one.py"], None, SUITE,
                                              select_tests.reader(self.root)),
                          "no map to read, yet something was picked")

    def test_the_suite_list_is_start_test_shs(self):
        listed = select_tests.suite_modules()
        self.assertIn("test_impact_map", listed)
        self.assertEqual(len(listed), len(set(listed)), "a module is listed twice")

    def test_the_repository_files_are_gits_own_list(self):
        listed = impact_map.repository_files(REPO)
        self.assertIn("LICENSE", listed)
        self.assertIn("scripts/python/amaze/tests/impact_map.py", listed)
        self.assertFalse([path for path in listed if "__pycache__" in path])


@unittest.skipIf(sys.version_info < (3, 12), "sys.monitoring arrived in Python 3.12")
class TheRecorderChargesEachTestWhatItRan(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="amaze_impact_")
        self.addCleanup(shutil.rmtree, self.root, True)
        with open(os.path.join(self.root, "impact_probe.py"), "w", encoding="utf-8") as handle:
            handle.write("def touch():\n    return (lambda: 1)()\n")
        sys.path.insert(0, self.root)
        self.addCleanup(sys.path.remove, self.root)
        self.addCleanup(sys.modules.pop, "impact_probe", None)
        import impact_probe
        self.probe = impact_probe

    def test_a_def_run_by_two_modules_is_charged_to_both(self):
        recorder = impact_map.Recorder(self.root, tool=sys.monitoring.COVERAGE_ID)
        if not recorder.start(audit=False):
            self.skipTest("the coverage tool id is taken in this process")
        try:
            recorder.enter("test_first")
            self.probe.touch()
            recorder.enter("test_second")
            self.probe.touch()
        finally:
            recorder.stop()
        for module in ("test_first", "test_second"):
            self.assertEqual({"touch"}, recorder.ran.get(module, {}).get("impact_probe.py"),
                             "%s ran touch and was not charged for it" % module)

    def test_a_read_is_charged_but_an_import_a_traceback_and_a_stopped_recorder_are_not(self):
        fresh = os.path.join(self.root, "impact_fresh.py")
        with open(fresh, "w", encoding="utf-8") as handle:
            handle.write("VALUE = 1\n")
        self.addCleanup(sys.modules.pop, "impact_fresh", None)
        importlib.invalidate_caches()    # the finder caches the folder listing; on Windows a file written this fast is not in it
        recorder = impact_map.Recorder(self.root, tool=sys.monitoring.COVERAGE_ID)
        if not recorder.start():
            self.skipTest("the coverage tool id is taken in this process")
        try:
            recorder.enter("test_reader")
            with open(os.path.join(self.root, "impact_probe.py"), encoding="utf-8") as handle:
                handle.read()
            import impact_fresh
            recorder.enter("test_traceback")
            linecache.clearcache()
            linecache.getline(fresh, 1)
            recorder.enter("test_inspect")
            linecache.clearcache()
            inspect.getsource(impact_fresh)
        finally:
            recorder.stop()
        with open(os.path.join(self.root, "impact_probe.py"), encoding="utf-8") as handle:
            handle.read()
        self.assertEqual({"test_reader": {"impact_probe.py"}, "test_inspect": {"impact_fresh.py"}},
                         recorder.opened,
                         "an import's or a traceback's source read was charged as a read, "
                         "inspect.getsource was not, or a stopped recorder kept charging")

    def test_a_def_run_while_loading_is_charged_to_the_statement_that_ran_it(self):
        with open(os.path.join(self.root, "impact_built.py"), "w", encoding="utf-8") as handle:
            handle.write("def build():\n    return [1]\n\n\nTABLE = build()\n")
        self.addCleanup(sys.modules.pop, "impact_built", None)
        importlib.invalidate_caches()    # the finder caches the folder listing; on Windows a file written this fast is not in it
        recorder = impact_map.Recorder(self.root, tool=sys.monitoring.COVERAGE_ID)
        if not recorder.start(audit=False):
            self.skipTest("the coverage tool id is taken in this process")
        try:
            import impact_built                                # noqa: F401
        finally:
            recorder.stop()
        self.assertEqual({("impact_built.py", 5)},
                         recorder.anchors.get(("impact_built.py", "build")))
        built = recorder.build(impact_map.snapshot(self.root, ["impact_built.py"]), 0)
        self.assertEqual([("impact_built.py", "TABLE")],
                         built["files"]["impact_built.py"]["loaded"]["build"])

    def test_each_test_and_fixture_is_charged_the_time_it_ran(self):
        recorder = impact_map.Recorder(self.root, tool=sys.monitoring.COVERAGE_ID)
        recorder.clock = iter([0.0, 1.0, 4.0, 6.0]).__next__
        if not recorder.start(audit=False):
            self.skipTest("the coverage tool id is taken in this process")
        recorder.enter("test_a.A")
        recorder.begin("test_a.A.test_1")
        recorder.stop()
        self.assertEqual({impact_map.LOADING: 1.0, "test_a.A": 3.0, "test_a.A.test_1": 2.0},
                         recorder.seconds)
        self.assertEqual(["test_a.A.test_1"], recorder.tests)

    def test_the_map_is_written_whole_with_the_loading_bucket_in_it(self):
        recorder = impact_map.Recorder(self.root)
        recorder.ran = {impact_map.LOADING: {"impact_probe.py": {"touch"}},
                        "test_a": {"impact_probe.py": {"touch", "gone"}}}
        path = os.path.join(self.root, "map.json")
        with mock.patch.object(impact_map, "repository_files", return_value=["impact_probe.py"]):
            recorder.save(path, 7)
        with open(path, encoding="utf-8") as handle:
            written = json.load(handle)
        self.assertEqual([impact_map.LOADING, "test_a"], written["keys"])
        self.assertEqual({"touch": [0, 1]},
                         {k: sorted(v) for k, v in
                          written["files"]["impact_probe.py"]["ran"].items()},
                         "a def the file no longer has was kept, or a module was dropped")
        self.assertEqual(7, written["testsRun"])
        self.assertFalse(os.path.exists(path + ".writing"))


if __name__ == "__main__":
    unittest.main()
