"""One repeating failure must not fill the log, and a new file starts from zero. ▸o/debug-engine"""

import ast
import importlib
import inspect
import json
import os
import shutil
import sys
import tempfile
import textwrap
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import debug  # noqa: E402
from amaze.helpers import hostos  # noqa: E402
from amaze.tests import check_log_leak  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401 - import redirects the debug log


class TestFloodGuard(unittest.TestCase):

    def setUp(self):
        """Point the module at a temp log, and put it back or later records vanish into a deleted dir."""
        self.tmp = tempfile.mkdtemp(prefix="amaze_flood_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.log = os.path.join(self.tmp, "flood.jsonl")
        was_on, was_path = debug.is_on(), debug.log_path()
        self.addCleanup(debug.configure, was_on, was_path)
        debug.configure(True, self.log)
        debug._crash_counts.clear()
        self.addCleanup(debug._crash_counts.clear)

    def _records(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def _raise_and_record(self, where="loop"):
        try:
            raise RuntimeError("Internal C++ object already deleted.")
        except RuntimeError as exc:
            debug.exception(where, exc)

    def test_identical_failure_is_rate_limited(self):
        for _ in range(3000):
            self._raise_and_record()
        written = [r for r in self._records() if r.get("cat") == "exception"]
        # 5 verbatim + markers at 10/100/1000/2000/3000, not 3000 records.
        self.assertLess(len(written), 20, "the flood was not contained")
        self.assertGreaterEqual(len(written), debug.FLOOD_VERBATIM)
        last = written[-1]
        self.assertEqual(last["data"].get("repeat_count"), 3000)
        self.assertEqual(
            last["data"].get("suppressed"), 3000 - len(written),
            "suppressed does not match the records actually written")

    def test_a_small_flood_still_reports_its_size(self):
        """A flood too small for the every-1000 marker must still leave its count."""
        for _ in range(100):
            self._raise_and_record(where="small")
        written = [r for r in self._records()
                   if r.get("cat") == "exception"
                   and "small" in json.dumps(r)]
        counts = [r["data"].get("repeat_count") for r in written
                  if r.get("data", {}).get("repeat_count")]
        self.assertTrue(
            counts, "a 100-occurrence flood left no count in the log at all")
        self.assertGreaterEqual(
            max(counts), 100,
            "the log understates a 100-occurrence flood as %s" % max(counts))

    def test_a_different_failure_is_never_suppressed(self):
        """A noisy neighbour must not hide an unrelated bug."""
        for _ in range(2000):
            self._raise_and_record(where="noisy")
        before = len(self._records())
        try:
            raise ValueError("something else entirely")
        except ValueError as exc:
            debug.exception("quiet", exc)
        after = self._records()
        self.assertEqual(len(after), before + 1)
        self.assertEqual(after[-1]["msg"], "quiet")

    def test_slot_crashes_are_guarded(self):
        """guarded() wraps mouse handlers - the fastest flood there is."""
        @debug.guarded("TestWidget.mouseMoveEvent")
        def _slot():
            raise AttributeError("'NoneType' object has no attribute 'x'")

        for _ in range(1500):
            with self.assertRaises(AttributeError):
                _slot()
        written = [r for r in self._records()
                   if "slot crash" in str(r.get("msg", ""))]
        self.assertLess(len(written), 12, "slot flood was not contained")
        self.assertTrue(written, "slot crashes stopped being recorded")


class TestPerPassBudget(TestFloodGuard):
    """Per-item records share one flood key, so a pass needs its own allowance."""

    def test_identical_per_item_records_go_dark_without_a_budget(self):
        for i in range(273):
            debug.event("file", "geo thumbnail", i=i)
        written = [r for r in self._records() if r.get("msg") == "geo thumbnail"]
        self.assertLess(
            len(written), 20,
            "the guard did not fire, so this test is not measuring the "
            "problem the budget exists to solve")

    def test_a_budget_gives_every_pass_a_fresh_allowance(self):
        seen = []
        for _ in range(2):
            debug.begin_pass("geo")
            spent = 0
            for _ in range(273):
                if debug.pass_budget("geo", 20):
                    spent += 1
            seen.append(spent)
        self.assertEqual(
            [20, 20], seen,
            "a second pass did not get its own allowance - that is the "
            "whole difference from the session-wide flood guard, which "
            "stays dark once spent")

    def test_a_budget_is_bounded_within_one_pass(self):
        debug.begin_pass("geo")
        spent = sum(1 for _ in range(273) if debug.pass_budget("geo", 20))
        self.assertEqual(20, spent, "the budget did not bound the pass")

    def test_two_passes_do_not_share_an_allowance(self):
        debug.begin_pass("a")
        debug.begin_pass("b")
        for _ in range(20):
            debug.pass_budget("a", 20)
        self.assertTrue(
            debug.pass_budget("b", 20),
            "spending one pass's budget silenced another's, so a busy "
            "pass would blind an unrelated one")


class TestOneRecordCarriesTheWholeList(TestFloodGuard):
    """Cleanup and quarantine name every file they moved - a sample cannot put one back."""

    def test_one_record_survives_where_per_item_records_would_not(self):
        moved = [["mat/%d.mat" % i, "quarantine/%d.mat" % i]
                 for i in range(23)]
        debug.event("cleanup", "files quarantined",
                    moved=len(moved), files=moved)
        records = [r for r in self._records()
                   if r.get("msg") == "files quarantined"]
        self.assertEqual(1, len(records))
        self.assertEqual(
            23, len(records[0]["data"]["files"]),
            "the record dropped moves - every one has to be here, "
            "because this is the only trace of where a file went")

    def test_the_moving_loops_write_no_per_item_record(self):
        """Source-derived: a regrown per-item record shares one flood key and goes dark."""
        import re
        here = os.path.dirname(os.path.abspath(__file__))
        package = os.path.dirname(here)
        for name, banned in (
                (os.path.join("core", "library.py"), "file quarantined"),
                (os.path.join("core", "repair.py"),
                 "file could not be moved aside")):
            with open(os.path.join(package, name), encoding="utf-8") as fh:
                body = fh.read()
            self.assertEqual(
                [], re.findall(re.escape('"%s"' % banned), body),
                "%s writes a per-item record inside the move loop again; "
                "it shares one flood key with every other move and goes "
                "dark after %d" % (name, debug.FLOOD_VERBATIM))


class TestLogIsolation(unittest.TestCase):
    """The suite raises on purpose and the crash tier is always on, so the redirect must be real."""

    def test_the_log_is_not_the_users(self):
        self.assertFalse(
            os.path.realpath(debug.log_path()).startswith(
                os.path.realpath(hostos.log_root())),
            "the suite is writing %s" % debug.log_path())

    def test_the_env_var_isolates_a_fresh_import(self):
        """`AMAZE_LOG_DIR` is read at IMPORT, so a module that never imports test_support is isolated too."""
        tmp = tempfile.mkdtemp(prefix="amaze_env_log_")
        self.addCleanup(shutil.rmtree, tmp, True)
        previous = os.environ.get("AMAZE_LOG_DIR")
        os.environ["AMAZE_LOG_DIR"] = tmp

        def restore():
            if previous is None:
                os.environ.pop("AMAZE_LOG_DIR", None)
            else:
                os.environ["AMAZE_LOG_DIR"] = previous
        self.addCleanup(restore)
        was_on, was_path = debug.is_on(), debug.log_path()
        self.addCleanup(debug.configure, was_on, was_path)
        importlib.reload(debug)
        self.assertEqual(tmp, debug.DEFAULT_DIR)
        self.assertTrue(debug.log_path().startswith(tmp))

    def test_redirect_does_not_turn_debug_mode_on(self):
        """A harness that flipped Debug Mode on would change the behaviour it observes."""
        tmp = tempfile.mkdtemp(prefix="amaze_redirect_")
        self.addCleanup(shutil.rmtree, tmp, True)
        was_on, was_path = debug.is_on(), debug.log_path()
        self.addCleanup(debug.configure, was_on, was_path)

        debug.configure(False, was_path)
        debug.redirect(os.path.join(tmp, "moved.jsonl"))
        self.assertFalse(debug.is_on(), "redirect() enabled verbose logging")
        self.assertEqual(os.path.join(tmp, "moved.jsonl"), debug.log_path())

        debug.event("test", "should not be written")
        self.assertFalse(os.path.exists(debug.log_path()))

        @debug.guarded("TestWidget.mouseReleaseEvent")
        def _slot():
            raise RuntimeError("crash tier is always on")

        with self.assertRaises(RuntimeError):
            _slot()
        self.assertTrue(os.path.exists(debug.log_path()),
                        "the crash tier stopped writing after a redirect")
        with open(debug.log_path(), encoding="utf-8") as handle:
            records = [json.loads(line) for line in handle if line.strip()]
        self.assertTrue(
            any("slot crash" in str(r.get("msg", "")) for r in records),
            "the crash landed somewhere other than the redirected file")
        self.assertFalse(
            any(r.get("cat") == "note" for r in records),
            "a redirect turned verbose logging on")


class TestLeakCheck(unittest.TestCase):
    """The isolation check itself: an open Houdini appending is fine, a headless process is not."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="amaze_leakcheck_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.log = os.path.join(self.tmp, "amaze_debug.jsonl")

    def _write(self, records) -> int:
        """Append records, return the byte offset BEFORE them."""
        offset = os.path.getsize(self.log) if os.path.exists(self.log) else 0
        with open(self.log, "a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")
        return offset

    @staticmethod
    def _header(session, product):
        return {"cat": "session", "msg": "session start",
                "data": {"product": product}, "session": session}

    @staticmethod
    def _record(session, cat="note"):
        return {"cat": cat, "msg": "something", "session": session}

    def test_an_open_houdini_is_not_a_leak(self):
        offset = self._write([self._header("s1", "hindie")])
        self._write([self._record("s1") for _ in range(5)])
        self.assertEqual([], check_log_leak.leaked_sessions(self.log, offset))

    def test_a_headless_session_is_a_leak(self):
        offset = self._write([
            self._header("s2", "hython"),
            self._record("s2", "exception"),
        ])
        leaks = check_log_leak.leaked_sessions(self.log, offset)
        self.assertEqual(1, len(leaks))
        session, product, count = leaks[0]
        self.assertEqual(("s2", "hython"), (session, product))
        self.assertEqual(2, count)

    def test_a_session_with_no_header_here_is_a_leak(self):
        """A process that starts elsewhere and switches here mid-run leaves its header in the OTHER file."""
        offset = self._write([self._record("orphan")])
        leaks = check_log_leak.leaked_sessions(self.log, offset)
        self.assertEqual([("orphan", "UNKNOWN", 1)], leaks)

    def test_historical_leaks_do_not_fail_todays_run(self):
        """The check is about what THIS run appended; the real log already holds historical leaks."""
        self._write([self._header("old", "hython"), self._record("old")])
        offset = self._write([self._header("now", "hindie")])
        self._write([self._record("now")])
        self.assertEqual([], check_log_leak.leaked_sessions(self.log, offset))


def _slate_fields():
    """(always, on_request): what `_blank_slate` blanks, read off its own source."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(debug._blank_slate)))

    def touched(statements):
        found = set()
        for statement in statements:
            for node in ast.walk(statement):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                    found.add(node.id)
                elif (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "clear"
                        and isinstance(node.func.value, ast.Name)):
                    found.add(node.func.value.id)
        return found

    body = tree.body[0].body
    return (touched([s for s in body if not isinstance(s, ast.If)]),
            touched([s for s in body if isinstance(s, ast.If)]))


class TheBlankSlate(unittest.TestCase):
    """What a switch to a new log file leaves behind, at all three doors. ▸p/log-blank-slate"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="amaze_slate_")
        was_on, was_path = debug.is_on(), debug.log_path()
        self.addCleanup(debug._blank_slate, True)
        self.addCleanup(debug.configure, was_on, was_path)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _dirty(self):
        """Every field the slate owns carrying something, whatever its type."""
        always, on_request = _slate_fields()
        for name in always | on_request:
            value = getattr(debug, name)
            if isinstance(value, dict):
                value["dirty"] = 1
            elif isinstance(value, set):
                value.add("dirty")
            elif isinstance(value, bool):
                setattr(debug, name, True)
            elif isinstance(value, int):
                setattr(debug, name, 4317)
            else:
                setattr(debug, name, "dirty")

    def _records(self, path):
        with open(path, encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def test_a_path_change_numbers_the_new_file_from_one(self):
        """`n` is a record's place in ITS OWN file, never the process's count."""
        first = os.path.join(self.tmp, "first.jsonl")
        second = os.path.join(self.tmp, "second.jsonl")
        debug.configure(True, first)
        for _ in range(5):
            debug.event("test", "filling the first file")
        debug.configure(True, second)
        debug.event("test", "the first record after the switch")
        numbers = [record["n"] for record in self._records(second)]
        self.assertEqual(
            1, min(numbers),
            "the new file continued the old one's numbering, opening at %d"
            % min(numbers))

    def test_the_whole_slate_is_blanked(self):
        """Derived from the helper, so a field joining the list is guarded that day."""
        always, _ = _slate_fields()
        self._dirty()
        debug.redirect(os.path.join(self.tmp, "moved.jsonl"))
        left = sorted(name for name in always if getattr(debug, name))
        self.assertEqual(
            [], left, "%s survived the move to a new file" % ", ".join(left))

    def test_an_alert_survives_a_move_and_dies_on_a_clear(self):
        """A dismissed dialog is a fact about the USER's session, not about logging."""
        debug.configure(True, os.path.join(self.tmp, "alerts.jsonl"))
        debug._alerted.add("thumbnail-failed")
        debug.redirect(os.path.join(self.tmp, "moved.jsonl"))
        self.assertIn("thumbnail-failed", debug._alerted,
                      "a redirect re-showed a dialog the user dismissed")
        debug.configure(True, os.path.join(self.tmp, "third.jsonl"))
        self.assertIn("thumbnail-failed", debug._alerted,
                      "a path change re-showed a dialog the user dismissed")
        self.assertEqual((True, ""), debug.clear_log())
        self.assertNotIn("thumbnail-failed", debug._alerted,
                         "Clear Log kept the alert history")

    def test_no_door_keeps_its_own_copy_of_the_list(self):
        """Three hand-kept copies is what left one door short of the record counter."""
        always, on_request = _slate_fields()
        owned = always | on_request
        found = []
        for scope in ast.walk(ast.parse(inspect.getsource(debug))):
            if (not isinstance(scope, ast.FunctionDef)
                    or scope.name not in ("clear_log", "configure", "redirect")):
                continue
            for node in ast.walk(scope):
                if (isinstance(node, ast.Name)
                        and isinstance(node.ctx, ast.Store)
                        and node.id in owned):
                    found.append("%s assigns %s" % (scope.name, node.id))
                elif (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "clear"
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id in owned):
                    found.append("%s clears %s"
                                 % (scope.name, node.func.value.id))
        self.assertEqual(
            [], sorted(found),
            "the slate is written outside _blank_slate: %s"
            % ", ".join(sorted(found)))


class TestExcepthookSurvivesReload(unittest.TestCase):
    """The crash recorder must survive a panel REOPEN without chaining to itself. ▸r/module-reload"""

    def setUp(self):
        self._real_hook = sys.excepthook
        self.addCleanup(setattr, sys, "excepthook", self._real_hook)
        for name in ("_excepthook_installed", "_previous_excepthook",
                     "_installed"):
            self.addCleanup(setattr, debug, name, getattr(debug, name))

    def _reopen_the_panel(self):
        """What a second panel open does to this module."""
        importlib.reload(debug)
        debug._install_excepthook()

    def test_the_hook_never_chains_to_itself(self):
        debug._install_excepthook()
        first = sys.excepthook
        self._reopen_the_panel()
        self.assertIsNot(
            debug._previous_excepthook, first,
            "the crash recorder chained to itself after a panel reopen - "
            "the next uncaught exception recurses to RecursionError")

    def test_a_crash_still_records_after_a_reopen(self):
        """The sentinel is planted BEFORE the first install, or it overwrites the self-reference this detects."""
        forwarded = []
        sys.excepthook = lambda *a: forwarded.append(a)
        debug._excepthook_installed = False
        debug._previous_excepthook = None
        debug._installed = False

        debug._install_excepthook()
        for _ in range(3):
            self._reopen_the_panel()

        limit = sys.getrecursionlimit()
        sys.setrecursionlimit(200)
        try:
            raise ValueError("a crash after three reopens")
        except ValueError:
            info = sys.exc_info()
            try:
                sys.excepthook(*info)
            except RecursionError:
                self.fail("the crash recorder recursed to death after a "
                          "panel reopen")
            finally:
                sys.setrecursionlimit(limit)

        self.assertEqual(
            1, len(forwarded),
            "the exception never reached Houdini's own excepthook")

    def test_reopening_does_not_re_arm_the_installer(self):
        debug._install_excepthook()
        importlib.reload(debug)
        self.assertTrue(
            debug._excepthook_installed,
            "the reload re-armed the installer; the flags must survive it")


if __name__ == "__main__":
    unittest.main()
