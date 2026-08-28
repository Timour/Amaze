"""Exporting the debug log for support - a deliberate act every time, never a background mirror, and its refusals are most of what is pinned here. ▸p/log-export"""

import os
import sys
import tempfile
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import debug  # noqa: E402
from amaze.helpers import hostos  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401 - redirects the log


class _Log:
    """A throwaway log file, and a throwaway place to export it to."""

    def __init__(self, testcase, contents='{"cat": "test"}\n'):
        self.tmp = tempfile.mkdtemp(prefix="amaze_export_")
        testcase.addCleanup(self._cleanup)
        self.source = os.path.join(self.tmp, "amaze_debug.jsonl")
        if contents is not None:
            with open(self.source, "w", encoding="utf-8") as fh:
                fh.write(contents)
        self.dest = os.path.join(self.tmp, "dest")
        os.makedirs(self.dest, exist_ok=True)
        real = debug.log_path
        testcase.addCleanup(setattr, debug, "log_path", real)
        debug.log_path = lambda: self.source

    def _cleanup(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestExportSucceeds(unittest.TestCase):

    def test_it_copies_the_log_byte_for_byte(self):
        log = _Log(self, contents='{"a": 1}\n{"b": 2}\n')
        target = debug.export_log(log.dest)
        self.assertTrue(os.path.isfile(target))
        with open(log.source, "rb") as a, open(target, "rb") as b:
            self.assertEqual(a.read(), b.read(),
                             "the export is not a faithful copy")

    def test_the_name_identifies_the_machine_os_and_houdini(self):
        """Two machines' logs must not collide, and must be told apart unopened."""
        log = _Log(self)
        name = os.path.basename(debug.export_log(log.dest))
        self.assertTrue(name.startswith("amaze-"), name)
        self.assertTrue(name.endswith(".jsonl"), name)
        self.assertIn(hostos.os_tag(), name)
        self.assertIn(hostos.machine_name(), name)
        self.assertIn("hou", name)

    def test_the_name_is_filename_safe(self):
        """A machine name carrying spaces, quotes or slashes must not break the path on the other OS."""
        log = _Log(self)
        real = hostos.machine_name
        self.addCleanup(setattr, hostos, "machine_name", real)
        name = os.path.basename(debug.export_log(log.dest))
        for bad in ("/", "\\", ":", " ", "'", "*", "?", '"'):
            self.assertNotIn(bad, name,
                             "%r is not safe in a filename: %s"
                             % (bad, name))

    def test_a_second_export_never_overwrites_the_first(self):
        """The stamp resolves only to the second, so a double-click would otherwise destroy the export just made."""
        log = _Log(self)
        first = debug.export_log(log.dest)
        second = debug.export_log(log.dest)
        self.assertNotEqual(first, second)
        self.assertTrue(os.path.isfile(first),
                        "the first export was overwritten")
        self.assertTrue(os.path.isfile(second))

    def test_it_creates_a_destination_that_does_not_exist_yet(self):
        log = _Log(self)
        fresh = os.path.join(log.tmp, "not", "there", "yet")
        target = debug.export_log(fresh)
        self.assertTrue(os.path.isfile(target))


class TestExportRefusesOutLoud(unittest.TestCase):
    """Every refusal carries its reason - a silent no-op teaches nothing. ▸p/log-export"""

    def test_no_log_yet_says_so_and_names_the_path(self):
        log = _Log(self, contents=None)
        with self.assertRaises(debug.ExportRefused) as caught:
            debug.export_log(log.dest)
        message = str(caught.exception)
        self.assertIn(log.source, message,
                      "the refusal did not say WHERE it looked")
        self.assertIn("Debug Mode", message,
                      "the refusal did not say what to do about it")

    def test_an_empty_log_is_refused_rather_than_exported(self):
        """Exporting a 0-byte file looks like success and hands over nothing."""
        log = _Log(self, contents="")
        with self.assertRaises(debug.ExportRefused) as caught:
            debug.export_log(log.dest)
        self.assertIn("empty", str(caught.exception).lower())

    def test_no_destination_is_refused(self):
        log = _Log(self)
        with self.assertRaises(debug.ExportRefused):
            debug.export_log("")

    def test_an_unwritable_destination_says_which_one(self):
        log = _Log(self)
        blocked = os.path.join(log.tmp, "blocked")
        os.makedirs(blocked, exist_ok=True)
        os.chmod(blocked, 0o500)
        self.addCleanup(os.chmod, blocked, 0o700)
        if os.access(blocked, os.W_OK):
            self.skipTest("this user can write to a read-only directory "
                          "(root?) - the case cannot be reproduced here")
        with self.assertRaises(debug.ExportRefused) as caught:
            debug.export_log(blocked)
        self.assertIn(blocked, str(caught.exception))

    def test_a_refusal_is_never_a_bare_falsy_return(self):
        """The distinction the class exists for: `nothing to export` must never read as `the export failed`."""
        log = _Log(self, contents=None)
        try:
            result = debug.export_log(log.dest)
        except debug.ExportRefused as exc:
            self.assertTrue(str(exc).strip(),
                            "ExportRefused was raised with no reason")
            return
        self.fail("export_log returned %r instead of refusing" % (result,))


class TestOsFacts(unittest.TestCase):

    def test_os_tag_is_one_of_the_known_names(self):
        self.assertIn(hostos.os_tag(),
                      ("macos", "windows", "linux", "unknown-os"))

    def test_machine_name_is_never_empty(self):
        """An empty name collapses two machines' exports into one filename shape."""
        self.assertTrue(hostos.machine_name())

    def test_machine_name_falls_back_rather_than_returning_nothing(self):
        real = os.environ.get("COMPUTERNAME")
        import platform as _platform
        real_node = _platform.node
        self.addCleanup(setattr, _platform, "node", real_node)
        _platform.node = lambda: ""
        os.environ.pop("COMPUTERNAME", None)
        os.environ.pop("HOSTNAME", None)
        if real is not None:
            self.addCleanup(os.environ.__setitem__, "COMPUTERNAME", real)
        self.assertTrue(hostos.machine_name(),
                        "machine_name returned nothing with no source "
                        "available - the export name would collide")


class NoteRespectsTheConsoleRuleTest(unittest.TestCase):
    """`debug.note` is the only safe sink on Windows and once printed unconditionally, so the one path meant to obey the rule broke it. ▸r/qt-windows-macos"""

    def _capture(self, windows):
        import io
        import contextlib
        from amaze.core import debug as debug_module
        from amaze.helpers import hostos
        original = hostos.is_windows
        hostos.is_windows = lambda: windows
        self.addCleanup(setattr, hostos, "is_windows", original)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            debug_module.note("a diagnostic line")
        return buffer.getvalue()

    def test_it_prints_on_a_mac(self):
        self.assertIn("a diagnostic line", self._capture(windows=False))

    def test_it_does_NOT_print_on_windows(self):
        self.assertEqual(
            "", self._capture(windows=True),
            "note() printed on Windows - that pops the Houdini Console "
            "window in front of the user's scene")

    def test_the_line_still_reaches_the_log_on_windows(self):
        from amaze.core import debug as debug_module
        written = []
        original = debug_module._write
        debug_module._write = written.append
        self.addCleanup(setattr, debug_module, "_write", original)
        debug_module._enabled = True
        self._capture(windows=True)
        self.assertTrue(
            any("a diagnostic line" == r.get("msg") for r in written),
            "suppressing the print also lost the line entirely")


class CapturedLogHelperTest(unittest.TestCase):
    """`test_support.captured_log()` - a capture helper returning nothing or anything silently inverts every assertion built on it, and it must leave Debug Mode as it found it. ▸p/captured-log-helper"""

    def test_it_captures_a_note(self):
        with test_support.captured_log() as log:
            debug.note("a captured diagnostic")
        self.assertEqual(
            ["a captured diagnostic"],
            log.matching("a captured diagnostic"),
            "captured_log() saw nothing, so every assertion made "
            "through it would fail whatever the code said")

    def test_it_captures_after_the_block_has_ended(self):
        """Where the first version failed: the tempdir went at exit and records were read lazily."""
        with test_support.captured_log() as log:
            debug.note("read me afterwards")
        self.assertTrue(log.matching("read me afterwards"))

    def test_it_does_not_invent_a_match(self):
        with test_support.captured_log() as log:
            debug.note("one thing happened")
        self.assertEqual([], log.matching("something else entirely"))

    def test_an_event_is_not_a_note(self):
        """The category filter is why a test can pin `the user was told` rather than `something was logged`."""
        with test_support.captured_log() as log:
            debug.event("test", "an internal detail")
        self.assertEqual([], log.messages())
        self.assertTrue(log.matching("an internal detail",
                                     category="test"))

    def test_debug_mode_is_restored(self):
        was_on = debug.is_on()
        with test_support.captured_log():
            self.assertTrue(debug.is_on(),
                            "captured_log did not turn Debug Mode on, so "
                            "note()'s log write stays gated off")
        self.assertEqual(
            was_on, debug.is_on(),
            "captured_log left Debug Mode changed - one use of it would "
            "reconfigure logging for every later test in the process")

    def test_debug_mode_is_restored_after_a_failure(self):
        was_on = debug.is_on()
        with self.assertRaises(ValueError):
            with test_support.captured_log():
                raise ValueError("a test failing inside the block")
        self.assertEqual(was_on, debug.is_on())

    def test_the_shared_test_log_is_put_back(self):
        with test_support.captured_log():
            pass
        self.assertEqual(
            test_support.TEST_LOG, debug._path,
            "captured_log left the log pointed at its own throwaway "
            "file, which is deleted - so nothing after it is recorded")


if __name__ == "__main__":
    unittest.main()
