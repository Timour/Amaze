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
from PySide6 import QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import debug  # noqa: E402
from amaze.helpers import hostos  # noqa: E402
from amaze.tests import check_log_leak  # noqa: E402
from amaze.tests import test_support  # noqa: E402 - import redirects the debug log


class _LogCase(unittest.TestCase):
    """A temp debug log for the flood tests; a base class with no tests, so none runs twice."""

    def setUp(self):
        """Point `debug` at a temp log, restored after, or later records go to a deleted dir."""
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


class TestFloodGuard(_LogCase):

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
        self.assertLess(len(written), 20, "the repeated failure was not rate-limited")
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
        """Rate-limiting one repeated failure must not suppress an unrelated one."""
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

    def test_the_three_crash_handlers_write_one_record_shape(self):
        """A slot, an uncaught raise and a handled one: the tenth record, field for field."""
        for name in ("_excepthook_installed", "_previous_excepthook"):
            self.addCleanup(setattr, debug, name, getattr(debug, name))
        self.addCleanup(setattr, sys, "excepthook", sys.excepthook)
        sys.excepthook = lambda *info: None
        debug._excepthook_installed = False
        debug._install_excepthook()

        @debug.guarded("Test.slot")
        def _slot():
            raise RuntimeError("deleted")

        for _ in range(10):
            with self.assertRaises(RuntimeError):
                _slot()
            try:
                raise RuntimeError("deleted")
            except RuntimeError as exc:
                sys.excepthook(type(exc), exc, exc.__traceback__)
                debug.exception("Test.handled", exc, row=3)
        tenth = {}
        for record in self._records():
            if record.get("cat") == "exception":
                tenth[record["msg"]] = record
        self.assertEqual(
            {"slot crash in Test.slot: RuntimeError":
                 {"value": "deleted", "repeat_count": 10, "suppressed": 4},
             "unhandled: RuntimeError":
                 {"value": "deleted", "repeat_count": 10, "suppressed": 4},
             "Test.handled": {"row": 3, "repeat_count": 10, "suppressed": 4}},
            {msg: record["data"] for msg, record in tenth.items()})
        self.assertTrue(all("RuntimeError: deleted" in record["traceback"]
                            for record in tenth.values()))


class TwoThreadsCountEveryOccurrence(_LogCase):
    """Convert worker threads and the UI thread log at once; a flood's final count must be exact."""

    def test_two_threads_logging_one_event_lose_no_count(self):
        import threading
        per_thread, start = 3000, threading.Barrier(2)

        def log():
            start.wait()
            for i in range(per_thread):
                debug.event("race", "same message", i=i)

        interval = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)    # switch threads as often as a busy Houdini does
        try:
            threads = [threading.Thread(target=log) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        finally:
            sys.setswitchinterval(interval)
        key = debug._flood_key("event:race", "same message", "")
        self.assertEqual(2 * per_thread, debug._crash_counts.get(key),
                         "the flood count lost increments")
        written = [r for r in self._records() if r.get("cat") == "race"]
        self.assertEqual(len(written), debug._crash_recorded.get(key),
                         "the recorded count is not what was written")


class TestPerPassBudget(_LogCase):
    """Per-item records share one flood key, so a pass needs its own allowance."""

    def test_identical_per_item_records_are_suppressed_without_a_budget(self):
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
            "stays silent once spent")

    def test_two_passes_do_not_share_an_allowance(self):
        debug.begin_pass("a")
        debug.begin_pass("b")
        for _ in range(20):
            debug.pass_budget("a", 20)
        self.assertTrue(
            debug.pass_budget("b", 20),
            "spending one pass's budget silenced another's, so a busy "
            "pass would silence an unrelated one")


class TestOneRecordHoldsTheWholeList(_LogCase):
    """Cleanup and quarantine log every moved file; a sample would not let one be restored."""

    def test_one_record_holds_all_23_moved_files(self):
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


class EveryFailedSaveWritesARecord(_LogCase):
    """A failed database save writes one record per call, however many fail in a row."""

    def _saves(self):
        return [r for r in self._records()
                if r.get("cat") == "database" and r.get("msg") == "save failed"]

    def test_six_failed_saves_in_a_row_each_write_a_record(self):
        import types
        from amaze.core import library_db, library_files
        library = tempfile.mkdtemp(prefix="amaze_flood_saves_")
        self.addCleanup(shutil.rmtree, library, True)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        holder = types.SimpleNamespace(dir=library + os.sep, library_user=test_support.FIXTURE_USER)
        held = library_db.document(holder, library_files.CODE)
        before = len(self._saves())
        with test_support.full_disk_for(os.path.join(library, library_files.CODE)):
            for n in range(6):
                held.put("assets", "snippet%d" % n, {"name": "snippet %d" % n})
                library_db.save(holder, library_files.CODE)
        self.assertEqual(
            before + 6, len(self._saves()),
            "save records went missing - they share one flood key, so "
            "the log stops after %d" % debug.FLOOD_VERBATIM)


class TestLogIsolation(unittest.TestCase):
    """The suite raises on purpose and the crash tier is always on, so the redirect must be real."""

    def test_the_suite_log_is_outside_the_users_log_folder(self):
        self.assertFalse(
            os.path.realpath(debug.log_path()).startswith(
                os.path.realpath(hostos.real_log_root())),
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
            "the crash record was written somewhere other than the redirected file")
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
    """(always, on_request): the names `_blank_slate` resets, parsed from its source."""
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
    """What `configure`, `redirect` and `clear_log` reset and keep. ▸p/log-blank-slate"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="amaze_slate_")
        was_on, was_path = debug.is_on(), debug.log_path()
        self.addCleanup(debug._blank_slate, True)
        self.addCleanup(debug.configure, was_on, was_path)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _dirty(self):
        """Set every field `_blank_slate` resets to a non-empty value of its type."""
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
        self.assertTrue(
            all(record.get("session") for record in self._records(second)),
            "records in the new file carry an EMPTY session id, so "
            "log-check.py shows the file as having zero sessions")

    def test_redirect_resets_every_field_blank_slate_resets(self):
        """Field list read from `_blank_slate`, so a field added there is checked at once."""
        always, _ = _slate_fields()
        self._dirty()
        debug.redirect(os.path.join(self.tmp, "moved.jsonl"))
        left = sorted(name for name in always if getattr(debug, name))
        self.assertEqual(
            [], left, "%s was not reset by the switch to a new file" % ", ".join(left))

    def test_a_dismissed_alert_is_kept_by_redirect_and_reset_by_clear_log(self):
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


class TestExcepthookWorksAfterReload(unittest.TestCase):
    """The excepthook works after a panel REOPEN and never calls itself. ▸r/module-reload"""

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

    def test_the_three_crash_counters_are_kept_together_through_a_reopen(self):
        """All three or none: a count reset against a kept `recorded` logs a negative suppressed count."""
        self.addCleanup(debug._crash_counts.clear)
        self.addCleanup(debug._crash_recorded.clear)
        debug._crash_counts["k"] = 100
        debug._crash_recorded["k"] = 7
        self._reopen_the_panel()
        self.assertEqual(
            debug._crash_counts.get("k"), 100,
            "the count reset on reload while its companions persisted - "
            "the flood counters no longer agree")

    def test_a_crash_still_records_after_a_reopen(self):
        """The sentinel is set before the first install, or it overwrites the self-reference."""
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
                self.fail("the excepthook raised RecursionError after a "
                          "panel reopen")
            finally:
                sys.setrecursionlimit(limit)

        self.assertEqual(
            1, len(forwarded),
            "the exception never reached Houdini's own excepthook")

    def test_a_reload_keeps_the_excepthook_installed_flag(self):
        debug._install_excepthook()
        importlib.reload(debug)
        self.assertTrue(
            debug._excepthook_installed,
            "the reload reset `_excepthook_installed`; the flags must survive it")


if __name__ == "__main__":
    unittest.main()
