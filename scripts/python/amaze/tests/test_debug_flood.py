"""One repeating failure must not fill the log.

A stale callback in a paint or timer path re-fires per event-loop tick.
The log has a session where that wrote 8,973 identical records - 8,996
events, of which 23 were anything else, which is a log that cannot be
read exactly when it matters most. Every path that records a traceback
is rate-limited: the first few in full, then one counting marker.
"""

import importlib
import json
import os
import shutil
import sys
import tempfile
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
        self.tmp = tempfile.mkdtemp(prefix="amaze_flood_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.log = os.path.join(self.tmp, "flood.jsonl")
        # Put the module back where it was afterwards - the isolated
        # suite log, verbose off. Leaving it pointed at this test's
        # temp dir (which cleanup then deletes) means any later record
        # in the same process goes nowhere and says nothing about it.
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
        # The count is reported, so the log still says how bad it got.
        last = written[-1]
        self.assertEqual(last["data"].get("repeat_count"), 3000)
        # "suppressed" is COUNTED, not inferred. It used to be
        # count - FLOOD_VERBATIM, which forgets that the marker records
        # themselves were kept, so it over-reported by one per marker.
        self.assertEqual(
            last["data"].get("suppressed"), 3000 - len(written),
            "suppressed does not match the records actually written")

    def test_a_small_flood_still_reports_its_size(self):
        """The gap that made this worth changing: markers fired only at
        multiples of 1000, so 100 occurrences wrote 5 records and said
        NOTHING about the other 95 - and log-check reported 5."""
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


class TestLogIsolation(unittest.TestCase):
    """The suite must not write the user's real log.

    guarded() and the excepthook record tracebacks with Debug Mode OFF -
    by design, a genuine crash is always worth a record. The cost was
    that tests which raise ON PURPOSE (this file raises 6,500 times; the
    drag suite raises inside a Qt slot deliberately) wrote crash records
    into the real log, until 18,975 of them made its exception count
    meaningless. Importing test_support redirects the log; these tests
    check the redirect is real, and that it did not turn verbose logging
    on as a side effect of moving the file."""

    def test_the_log_is_not_the_users(self):
        self.assertFalse(
            os.path.realpath(debug.log_path()).startswith(
                os.path.realpath(hostos.log_root())),
            "the suite is writing %s" % debug.log_path())

    def test_the_env_var_isolates_a_fresh_import(self):
        """The runner exports AMAZE_LOG_DIR before any module loads;
        debug reads it at import, so even a module that never imports
        test_support is isolated. Proved by re-importing the module."""
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
        # A reload re-runs the module body, which is where the variable
        # is read - the same thing a fresh process does.
        was_on, was_path = debug.is_on(), debug.log_path()
        self.addCleanup(debug.configure, was_on, was_path)
        importlib.reload(debug)
        self.assertEqual(tmp, debug.DEFAULT_DIR)
        self.assertTrue(debug.log_path().startswith(tmp))

    def test_redirect_does_not_turn_debug_mode_on(self):
        """configure() is the user's switch; redirect() only moves the
        file. A test harness that flipped Debug Mode on would change the
        behaviour it is trying to observe."""
        tmp = tempfile.mkdtemp(prefix="amaze_redirect_")
        self.addCleanup(shutil.rmtree, tmp, True)
        was_on, was_path = debug.is_on(), debug.log_path()
        self.addCleanup(debug.configure, was_on, was_path)

        debug.configure(False, was_path)
        debug.redirect(os.path.join(tmp, "moved.jsonl"))
        self.assertFalse(debug.is_on(), "redirect() enabled verbose logging")
        self.assertEqual(os.path.join(tmp, "moved.jsonl"), debug.log_path())

        # Verbose records stay dropped (event/note/exception are all
        # Debug-Mode gated)...
        debug.event("test", "should not be written")
        self.assertFalse(os.path.exists(debug.log_path()))

        # ...while the ALWAYS-ON crash tier still writes, into the NEW
        # file. guarded() is that tier, and the exact path that leaked:
        # it wraps the mouse handlers, so the drag suite's deliberate
        # failure was recorded no matter what Debug Mode said.
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
    """The check that guards the isolation, checked itself.

    It has to tell two appending processes apart: the user's Houdini,
    which may well be open while the suite runs, and a headless test
    process, which must never touch this file. Synthetic logs, because
    the real one is exactly what these tests must not write to."""

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
        """The shape a product check alone would miss: a process that
        starts logging elsewhere and switches to this file mid-run, so
        its header is in the OTHER file."""
        offset = self._write([self._record("orphan")])
        leaks = check_log_leak.leaked_sessions(self.log, offset)
        self.assertEqual([("orphan", "UNKNOWN", 1)], leaks)

    def test_historical_leaks_do_not_fail_todays_run(self):
        """95 headless sessions are already in the real log. The check
        is about what THIS run appended, or it can never pass."""
        self._write([self._header("old", "hython"), self._record("old")])
        offset = self._write([self._header("now", "hindie")])
        self._write([self._record("now")])
        self.assertEqual([], check_log_leak.leaked_sessions(self.log, offset))


class TestExcepthookSurvivesReload(unittest.TestCase):
    """The crash recorder must survive a panel REOPEN.

    panel.py reloads every amaze module on open so edits take effect
    without restarting Houdini, and importlib.reload re-executes the
    module body into the SAME module dict. debug.py reset
    _excepthook_installed and _previous_excepthook there, while the hook
    installed by the previous open was still sys.excepthook - and that
    closure reads _previous_excepthook out of the shared dict at call
    time. So the second install stored the OLD HOOK as its own previous,
    and the hook chained to itself.

    Effect: from the second panel open onward, the next uncaught
    exception recursed to RecursionError, Houdini's own excepthook never
    ran, and the log got a truncated record instead of a traceback. The
    recorder died exactly when it was needed - and this project's
    working rule is to read that log on every symptom report."""

    def setUp(self):
        self._real_hook = sys.excepthook
        self.addCleanup(setattr, sys, "excepthook", self._real_hook)
        # Restore the module's own flags too - this test deliberately
        # drives the install path, and the flags now survive reload.
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
        """The behaviour, not just the wiring: three reopens, then fire
        a real exception through sys.excepthook.

        The sentinel is planted BEFORE the first install so it becomes
        the legitimate bottom of the chain. Planting it afterwards would
        overwrite the very self-reference this is meant to detect - the
        first version of this test did that and stayed green under
        sabotage."""
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
