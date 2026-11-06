"""The suite reads no machine files: no test builds its own panel, every scanned dir is temp."""

import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou                                                     # noqa: E402,F401

import test_support                                            # noqa: E402


HERE = os.path.dirname(os.path.abspath(__file__))


def _test_modules():
    for name in sorted(os.listdir(HERE)):
        if name.startswith("test_") and name.endswith(".py"):
            yield name


class NoTestBuildsItsOwnPanel(unittest.TestCase):
    """Building the panel directly reads the real settings and library; asserted as an empty set."""

    ALLOWED = {"test_support.py"}

    def test_no_test_module_constructs_a_panel_directly(self):
        with open(os.path.join(HERE, "test_support.py"),
                  encoding="utf-8") as handle:    # anti-vacuity: the needle must still find its haystack
            self.assertTrue(
                re.findall(r"AmazePanel\s*\(", handle.read()),
                "the pattern no longer matches a real panel construction - "
                "re-key it in this same change, or it is checking nothing")
        offenders = {}
        for name in _test_modules():
            if name in self.ALLOWED:
                continue
            with open(os.path.join(HERE, name), encoding="utf-8") as handle:
                body = handle.read()
            hits = re.findall(r"AmazePanel\s*\(", body)
            if hits:
                offenders[name] = len(hits)
        self.assertEqual(
            {}, offenders,
            "these test modules build a panel directly instead of "
            "through test_support.fixture_panel, so they open the "
            "machine's real library and its real file locations: %s"
            % offenders)


class AFixturePanelScansNothingOfTheUsers(unittest.TestCase):
    """The runtime half: every directory the panel would walk is temp."""

    def test_every_registered_location_is_inside_the_temp_dir(self):
        panel = test_support.fixture_panel(self)
        temp = os.path.realpath(tempfile.gettempdir())

        registered = []
        self.assertTrue(    # the accept path: a guard only ever satisfied by emptiness is not a guard
            list(panel.prefs.file_folders),
            "the fixture panel registers no file location, so this "
            "guard passes for the wrong reason")
        # NAMED, never `getattr(..., ())` - defaulting narrows this guard.
        for folder in panel.prefs.file_folders or ():
            registered.append(("file_folders", str(folder)))
        registered.append(("library", panel.prefs.dir))
        registered.append(("settings", panel.prefs.path))

        outside = [(k, p) for k, p in registered
                   if not os.path.realpath(p).startswith(temp)]
        self.assertEqual(
            [], outside,
            "a fixture panel is pointed at directories outside the temp "
            "dir - it would scan the machine's own files: %s" % outside)


class TheSnapshotToolFingerprintsALibrary(unittest.TestCase):
    """Armed, the machine's settings are out of reach, so `ui_snapshot.py` needs its own library."""

    def test_the_snapshot_grid_has_a_model_with_rows(self):
        from amaze.tests import ui_snapshot

        folder = test_support.scratch_dir("amaze_test_snapshot_")
        self.addCleanup(shutil.rmtree, folder, True)
        out = os.path.join(folder, "after.json")
        argv = ["ui_snapshot.py", "--out", out]
        with mock.patch.object(sys, "argv", argv), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, ui_snapshot.main())
        with open(out, encoding="utf-8") as handle:
            widgets = json.load(handle)["widgets"]
        grids = {path: entry for path, entry in widgets.items()
                 if path.endswith("/thumbview")}
        self.assertTrue(grids, "the snapshot holds no thumbview to check")
        for path, entry in grids.items():
            self.assertTrue(
                entry["model"] and entry["rows"],
                "%s has model %r and %r rows, so the snapshot is of a "
                "panel with no library" % (path, entry["model"],
                                           entry["rows"]))


class TheSUITETestsTheCheckoutAndNotTheInstall(unittest.TestCase):
    """The first import binds `amaze` for the process, so the checkout must come before the install."""

    def test_the_amaze_package_is_the_one_beside_these_tests(self):
        import amaze

        # The checkout this file belongs to, never a configured path.
        expected = os.path.dirname(HERE)
        loaded = os.path.dirname(os.path.abspath(amaze.__file__))
        self.assertEqual(
            expected, loaded,
            "the suite is testing a DIFFERENT copy of amaze than the "
            "one it lives in - every result is about\n  %s\nwhile the "
            "working tree is\n  %s\nA sabotage in the checkout cannot "
            "turn anything red." % (loaded, expected))


if __name__ == "__main__":
    unittest.main()
