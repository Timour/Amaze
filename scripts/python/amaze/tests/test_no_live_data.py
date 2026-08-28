"""The suite must not read the machine's own files - PROVEN, not assumed, because a run that quietly scans a real photograph archive modifies nothing, fails nothing and says nothing. Two independent checks: a SOURCE one, that no test builds a panel directly, and a RUNTIME one, that every directory the models would scan is inside the temp dir. ▸archive/test_no_live_data.py
"""

import os
import re
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets                                  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou                                                     # noqa: E402,F401

import test_support                                            # noqa: E402


HERE = os.path.dirname(os.path.abspath(__file__))


def _test_modules():
    for name in sorted(os.listdir(HERE)):
        if name.startswith("test_") and name.endswith(".py"):
            yield name


class NoTestBuildsItsOwnPanel(unittest.TestCase):
    """Building the panel class directly reads the machine's real settings, and through them the real library. Asserted as an empty SET, never a count, or the check goes vacuous the day the constructor is renamed."""

    ALLOWED = {"ui_snapshot.py", "test_support.py"}

    def test_no_test_module_constructs_a_panel_directly(self):
        offenders = {}
        for name in _test_modules():
            if name in self.ALLOWED:
                continue
            with open(os.path.join(HERE, name), encoding="utf-8") as handle:
                body = handle.read()
            hits = re.findall(r"MatLibPanel\s*\(", body)
            if hits:
                offenders[name] = len(hits)
        self.assertEqual(
            {}, offenders,
            "these test modules build a panel directly instead of "
            "through test_support.fixture_panel, so they open the "
            "machine's real library and its real file locations: %s"
            % offenders)

    def test_the_check_can_actually_see_a_panel_construction(self):
        """Anti-vacuity - a source scan keyed on a name goes QUIET rather than red when the name changes, so the needle must be shown to still find its haystack."""
        with open(os.path.join(HERE, "test_support.py"),
                  encoding="utf-8") as handle:
            body = handle.read()
        self.assertTrue(
            re.findall(r"MatLibPanel\s*\(", body),
            "the pattern no longer matches a real panel construction - "
            "re-key it in this same change, or it is checking nothing")


class AFixturePanelScansNothingOfTheUsers(unittest.TestCase):
    """The runtime half: every directory the panel would walk is temp."""

    def test_every_registered_location_is_inside_the_temp_dir(self):
        panel = test_support.fixture_panel(self)
        temp = os.path.realpath(tempfile.gettempdir())

        registered = []
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

    def test_the_fixture_actually_registers_a_location(self):
        """The accept path - no locations also passes the test above, and a guard only ever satisfied by emptiness is not a guard."""
        panel = test_support.fixture_panel(self)
        self.assertTrue(
            list(panel.prefs.file_folders),
            "the fixture panel registers no file location, so the File "
            "section is untested and this file's other test passes for "
            "the wrong reason")

    def test_the_fixture_location_holds_every_kind(self):
        """And it must hold something of each KIND, or the section is exercised against an empty folder."""
        from amaze.core import file_library

        panel = test_support.fixture_panel(self)
        folder = list(panel.prefs.file_folders)[0]
        kinds = {file_library.kind_for(name)
                 for name in os.listdir(str(folder))}
        for expected in (file_library.KIND_IMAGE, file_library.KIND_GEO,
                         file_library.KIND_HIP, file_library.KIND_OTHER):
            self.assertIn(
                expected, kinds,
                "the fixture file location has no %s in it, so that "
                "branch of the File section is never reached" % expected)


class TheSUITETestsTheCheckoutAndNotTheInstall(unittest.TestCase):
    """Which COPY of the package is under test. hython's own path holds the INSTALLED one, and the FIRST import to reach `amaze` binds it for the whole process - so a single module without the checkout in front tests the last sync and reads as a pass."""

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
