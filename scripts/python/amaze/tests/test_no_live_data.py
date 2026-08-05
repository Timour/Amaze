"""The suite must not read the machine's own files. Proven, not assumed.

2026-08-02. A panel test called `activate()` on every section against
the REAL library, and the File section's activate SCANS every
registered location and converts every image in it. On this machine
those locations are personal photograph and texture archives, so a
column-width assertion spent ten minutes grinding through thousands of
somebody's photographs. Nothing was modified and nothing failed - which
is exactly the problem, because nothing said a word either.

`_protect_live_settings` was the guard in use, and it was never enough:
it disables `Prefs.save` and redirects the log, so the SETTINGS FILE is
safe while the panel still opens the real library and the real
locations recorded in it. `fixture_panel` is the one that isolates all
of it, and these tests are what stop a class drifting back.

Two independent checks, because they fail differently:

* a SOURCE check - no test may construct a panel directly, which is the
  only way to get one that is not isolated;
* a RUNTIME check - walk every directory the panel models would scan
  and require each to be inside the temp dir.
"""

import os
import re
import tempfile
import unittest

# The offscreen QApplication has to exist before anything builds a
# QWidget, and fixture_panel builds a whole panel. Same three lines as
# every other panel-touching module here.
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
    """Constructing the panel class directly reads the machine's real
    settings.json, and through it the real library and the real File
    locations. (Spelled around rather than written out: this module is
    scanned by its own check, and a mention in prose is a match.)

    Asserted as an empty SET rather than a count: "found none" and
    "every module is clean" have to be different answers, or the check
    goes vacuous the day the constructor is renamed.
    """

    #: The only non-test caller. It exists to snapshot the REAL panel
    #: for the design handoff - that is its whole job, it is run by
    #: hand, and it is not part of the suite.
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
        """Anti-vacuity: the pattern above must match the real thing.

        A source scan keyed on a name goes quiet rather than red when
        the name changes, so prove the needle still finds the haystack
        it was written for."""
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
        for kind in ("file_folders", "texture_folders", "geometry_folders",
                     "hip_folders"):
            for folder in getattr(panel.prefs, kind, ()) or ():
                registered.append((kind, str(folder)))
        registered.append(("library", panel.prefs.dir))
        registered.append(("settings", panel.prefs.path))

        outside = [(k, p) for k, p in registered
                   if not os.path.realpath(p).startswith(temp)]
        self.assertEqual(
            [], outside,
            "a fixture panel is pointed at directories outside the temp "
            "dir - it would scan the machine's own files: %s" % outside)

    def test_the_fixture_actually_registers_a_location(self):
        """Accept-path half. "No locations" also passes the test above,
        and would mean the File section is never exercised at all -
        a guard that is only ever satisfied by emptiness is not a
        guard, and it would have hidden the very tab that caused this.
        """
        panel = test_support.fixture_panel(self)
        self.assertTrue(
            list(panel.prefs.file_folders),
            "the fixture panel registers no file location, so the File "
            "section is untested and this file's other test passes for "
            "the wrong reason")

    def test_the_fixture_location_holds_every_kind(self):
        """And it has to contain something of each KIND, or the section
        is 'exercised' against an empty folder."""
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


if __name__ == "__main__":
    unittest.main()
