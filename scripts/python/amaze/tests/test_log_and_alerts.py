"""Log and alerts: one test per requirement in docs/requirements/log-and-alerts.md."""

import datetime
import errno
import importlib
import json
import os
import shutil
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

from amaze.core import debug
from amaze.helpers import hostos
from amaze.tests import test_support

STAMP = datetime.datetime(2026, 11, 24, 10, 0, 0)


class _Log(unittest.TestCase):
    """A log file of its own with Debug Mode on, a folder to export to, and a UI that records."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_log_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.log, self.out = os.path.join(self.dir, "log.jsonl"), os.path.join(self.dir, "out")
        self.addCleanup(debug.configure, debug.is_on(), test_support.TEST_LOG)
        self.addCleanup(debug.set_ui, debug._ui)
        self.addCleanup(debug._alerted.clear)
        debug.configure(True, self.log)
        self.shown = {"dialog": [], "status": []}
        debug.set_ui(types.SimpleNamespace(dialog=self.shown["dialog"].append,
                                           status=self.shown["status"].append,
                                           houdini_version=lambda: "22.0.466",
                                           describe=lambda info: None))

    def records(self, category=None) -> list:
        with open(self.log, encoding="utf-8") as handle:
            found = [json.loads(line) for line in handle if line.strip()]
        return [one for one in found if category is None or one.get("cat") == category]

    def crash(self, frame: str = "frame") -> None:
        debug._record_crash("unhandled", "RuntimeError", "Traceback\n  %s\nRuntimeError" % frame,
                            "unhandled: RuntimeError", {})


class LogTest(_Log):
    """Requirements on what the log holds."""

    def test_lg01_an_export_never_writes_over_a_file_in_the_folder(self):
        debug.event("test", "something to export")
        clock = types.SimpleNamespace(datetime=types.SimpleNamespace(now=lambda: STAMP))
        with mock.patch.object(debug, "datetime", clock):
            first = debug.export_log(self.out)
            theirs = os.path.join(self.out, os.path.basename(first)[:-6] + "-1.jsonl")
            test_support.put(self.out, os.path.basename(theirs), b"the user's own file")
            with open(first, "rb") as handle:
                exported = handle.read()
            second = debug.export_log(self.out)
        self.assertEqual(3, len({first, theirs, second}), "an export took another file's name")
        with open(theirs, "rb") as handle:
            self.assertEqual(b"the user's own file", handle.read())
        with open(first, "rb") as handle:
            self.assertEqual(exported, handle.read(), "the first export was written over")

    def test_lg10_logging_never_raises_and_never_fills_the_disk(self):
        debug.redirect(os.path.join(self.dir, "a file", "log.jsonl"))
        test_support.put(self.dir, "a file", b"not a folder")
        debug.event("test", "a write that fails")
        self.crash()
        debug.configure(True, self.log)
        with mock.patch.object(debug, "MAX_BYTES", 4000), \
                mock.patch.object(debug, "_SIZE_CHECK_EVERY", 1):
            for number in range(200):
                debug.event("test", "event %d" % number, padding="x" * 100)
            kept = sorted(name for name in os.listdir(self.dir) if name.startswith("log"))
            self.assertEqual(["log.jsonl.1"], kept[-1:], "no older copy, or more than one")
            for name in kept:
                self.assertLess(os.path.getsize(os.path.join(self.dir, name)), 4000 + 400, name)
            test_support.put(self.dir, "log.jsonl", b"x" * 5000)
            with mock.patch("os.replace", side_effect=PermissionError), \
                    mock.patch("shutil.copyfile", side_effect=PermissionError):
                debug.redirect(self.log)
                debug.event("test", "the log is full and cannot be rotated")
                full = os.path.getsize(self.log)
                for number in range(50):
                    self.crash("frame %d" % number)
            self.assertEqual(full, os.path.getsize(self.log), "a full log kept growing")
        debug.configure(True, os.path.join(self.dir, "loop.jsonl"))
        for _ in range(10000):
            self.crash()
        with open(os.path.join(self.dir, "loop.jsonl"), encoding="utf-8") as handle:
            self.assertLess(len(handle.readlines()), 30, "a failure in a loop filled the log")

    def test_lg20_an_uncaught_error_is_recorded_and_houdini_still_handles_it(self):
        handled = []
        with mock.patch.object(sys, "excepthook", lambda *info: handled.append(info)), \
                mock.patch.object(debug, "_excepthook_installed", False), \
                mock.patch.object(debug, "_previous_excepthook", None):
            debug._install_excepthook()
            importlib.reload(debug)    # a pane opened again reloads the module ▸r/module-reload
            debug._install_excepthook()
            debug.configure(False, self.log)
            try:
                raise ValueError("an uncaught error")
            except ValueError:
                sys.excepthook(*sys.exc_info())
        debug.event("test", "Debug Mode is off")
        self.assertEqual(1, len(handled), "Houdini's own handling did not run once")
        self.assertEqual(["unhandled: ValueError"], [one["msg"] for one in self.records()
                                                     if one["cat"] != "session"])

    def test_lg21_a_repeated_failures_count_is_exact_from_any_thread(self):
        start = threading.Barrier(4)

        def loop():
            start.wait()
            for _ in range(2500):
                self.crash()
        threads = [threading.Thread(target=loop) for _ in range(4)]
        self.addCleanup(sys.setswitchinterval, sys.getswitchinterval())
        sys.setswitchinterval(1e-6)    # threads switch as often as a busy Houdini's do
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        debug.flush_repeats()    # what Houdini quitting runs
        self.crash("another")
        later = debug.time.monotonic() + debug.REPEAT_DECAY_SECONDS + 1
        for _ in range(9):
            self.crash("another")
        with mock.patch.object(debug.time, "monotonic", return_value=later):
            self.crash("another")    # it went quiet: its total is written first
        totals = [one["data"]["repeat_count"] for one in self.records()
                  if one["msg"].endswith("(final count)")]
        self.assertEqual([10000, 10], totals)


class AlertTest(_Log):
    """Requirements on what the user is shown."""

    def test_lg22_each_alert_shows_once_and_is_logged_every_time(self):
        for _ in range(3):
            debug.alert("The library could not be written.", key="write-failed")
        debug.alert("Another problem.")
        self.assertEqual(["The library could not be written.", "Another problem."],
                         self.shown["dialog"])
        self.assertEqual(4, len(self.records("alert")))

    def test_lg23_a_failed_action_goes_to_the_status_line_and_damage_to_a_dialog(self):
        for _ in range(2):
            debug.refuse("Drop a material on a network.")
        debug.refuse(debug.Damage("The library's database cannot be read."))
        self.assertEqual(["Drop a material on a network."] * 2, self.shown["status"])
        self.assertEqual(["The library's database cannot be read."], self.shown["dialog"])

    def test_lg24_export_copies_the_whole_log_under_a_telling_name_or_says_why(self):
        debug.event("test", "something to export")
        with open(self.log, "rb") as handle:
            whole = handle.read()
        exported = debug.export_log(self.out)
        with open(exported, "rb") as handle:
            self.assertEqual(whole, handle.read())
        name = os.path.basename(exported)
        for part in (hostos.machine_name(), hostos.os_tag(), "hou22-0-466"):
            self.assertIn(part, name)
        refused = test_support.scratch_dir("amaze_log_refused_")
        self.addCleanup(shutil.rmtree, refused, True)
        for log in (os.path.join(self.dir, "none.jsonl"), test_support.put(self.dir, "empty", b"")):
            debug.redirect(log)
            with self.assertRaises(debug.ExportRefused):
                debug.export_log(refused)
        debug.redirect(self.log)
        debug.event("test", "something to export")
        full = OSError(errno.ENOSPC, "No space left on device")
        with self.assertRaises(debug.ExportRefused), \
                mock.patch("shutil.copyfileobj", side_effect=full):
            debug.export_log(refused)
        with self.assertRaises(debug.ExportRefused):
            debug.export_log(os.path.join(test_support.put(self.dir, "plain", b""), "out"))
        self.assertEqual([], os.listdir(refused), "a refused export wrote a file")

if __name__ == "__main__":
    unittest.main(verbosity=2)
