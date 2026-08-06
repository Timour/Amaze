"""The viewport pick's coordinate space, per Houdini build.

queryNodeAtPixel does not apply the device pixel ratio on builds before
22.0.391 - that is what SideFX's changelog means by picking being broken
"on macOS retina displays" - so those builds want the point already
multiplied by it. Same origin, same convention as 22.0.393; one factor
apart.

Two lessons are pinned here as much as the behaviour:

- **One probe sample is not an answer.** A single earlier record said
  "logical, top-left", and a fix shipped on it. The cursor in that
  sample was near the bottom-right CORNER rather than on the sphere, so
  the candidate that hit did so by landing mid-viewport where the
  sphere happened to be. One candidate hitting looks identical to one
  candidate being right.
- **A viewport reports DEVICE pixels; Qt reports LOGICAL ones.** The
  stubs below model that, because a stub that reports logical sizes
  agrees with the bug instead of catching it.

22.0.393 picks correctly today and is not changed by any of this.
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import dragengine  # noqa: E402
from amaze.helpers import hostos  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401 - redirects the log


class _Viewport:
    """One viewport that records the pixel it was asked about.

    It reports its size the way Houdini actually does: FOUR values, in
    DEVICE pixels. A 481x279 widget at dpr 2.0 reports (0, 0, 962, 558),
    from the real log. The first version of this stub reported logical
    values - the same assumption that produced the bug - so the test
    agreed with the code about something they were both wrong about."""

    def __init__(self, w=481, h=279, scale=2.0, hit=None):
        self._device = (0, 0, int(w * scale), int(h * scale))
        self.asked = []
        self.hit = hit                    # (x, y) that returns a node

    def size(self):
        return self._device

    def queryNodeAtPixel(self, x, y, **kwargs):
        self.asked.append((x, y))
        if self.hit is not None and (x, y) == self.hit:
            return _Node("/obj/sphere_object1")
        return None


class _Node:
    def __init__(self, path):
        self._path = path

    def path(self):
        return self._path


class _Viewer:
    def __init__(self, vp):
        self._vp = vp

    def viewports(self):
        return (self._vp,)

    def curViewport(self):
        return self._vp


class _Version:
    """Pin hou.applicationVersion for the duration of a test.

    Real builds, because the gate keys on the build number: 21.0.780 is
    the one measured, 22.0.393 is the one that works, and 22.0.390 is
    the build immediately before SideFX's Retina picking fix."""

    BUILDS = {21: (21, 0, 780), 22: (22, 0, 393)}

    def __init__(self, testcase, major):
        self.major = major
        version = self.BUILDS.get(major, (major, 0, 0)) \
            if not isinstance(major, tuple) else major
        real = hou.applicationVersion
        testcase.addCleanup(setattr, hou, "applicationVersion", real)
        hou.applicationVersion = lambda: version


class _Platform:
    """Pin the OS for the duration of a test.

    The workaround is macOS-only - SideFX scoped the bug to "macOS
    retina displays" - and Windows reports scale factors too, 150%
    being its common default. Without a platform condition the
    workaround fires on Windows and breaks picking on a viewport that
    never had the bug."""

    def __init__(self, testcase, name):
        for attr, value in (("is_macos", name == "macos"),
                            ("is_windows", name == "windows"),
                            ("is_linux", name == "linux")):
            real = getattr(hostos, attr)
            testcase.addCleanup(setattr, hostos, attr, real)
            setattr(hostos, attr, (lambda v=value: v))


class TestPickCoordinateSpace(unittest.TestCase):
    """A 481x279 widget at dpr 2.0 - the real geometry from the log."""

    HEIGHT = 279
    SCALE = 2.0

    def _pick_with(self, version, x=441, gl_y=2, os_name="macos",
                   scale=None):
        _Version(self, version)
        _Platform(self, os_name)
        scale = self.SCALE if scale is None else scale
        vp = _Viewport(h=self.HEIGHT, scale=scale)
        dragengine._pick(_Viewer(vp), "obj", x, gl_y, scale, self.HEIGHT)
        self.assertEqual(1, len(vp.asked),
                         "the pick did not reach queryNodeAtPixel - this "
                         "test is not exercising the case it was written for")
        return vp.asked[0]

    def test_h21_is_asked_in_device_pixels(self):
        """Measured on 21.0.780: cursor ON the sphere at (292, 136),
        and only the device candidates returned the node."""
        self.assertEqual(
            (882, 4), self._pick_with(21),
            "21.0.780 does not apply the device pixel ratio itself, so "
            "the point must arrive already scaled")

    def test_h22_is_asked_in_logical_pixels(self):
        """The user's constraint, in a test: H22 works, so H22 does not
        change. Without this, a later 'simplification' that drops the
        build gate looks harmless and breaks the version that was never
        broken."""
        self.assertEqual(
            (441, 2), self._pick_with(22),
            "H22's pick coordinates changed - it was picking correctly "
            "with the unscaled logical point")

    def test_the_two_builds_actually_differ(self):
        """Guards the guard: if both branches ever return the same
        point, the two tests above pass while proving nothing."""
        self.assertNotEqual(
            self._pick_with(21), self._pick_with(22),
            "both builds now get the same coordinates - the tests above "
            "no longer distinguish the two conventions")

    def test_the_whole_h22_series_behaves_like_the_h22_we_measured(self):
        """The breakpoint sits at 22.0.0, NOT at the changelog's
        22.0.391.

        This test used to assert the opposite - that 22.0.390 needs the
        workaround - which was an INFERENCE from the changelog written
        down as though it were a measurement. No 22.0.x build below 393
        has ever run here.

        The asymmetry is the whole argument: leaving a host bug
        unworked-around on an untested build costs the user a bug they
        would have had anyway, while applying an untested workaround to
        a build that works breaks something that was fine."""
        for build in ((22, 0, 0), (22, 0, 390), (22, 0, 391),
                      (22, 0, 393), (22, 0, 394)):
            self.assertEqual(
                (441, 2), self._pick_with(build),
                "%s got the workaround - the H22 series must behave "
                "like the H22 that was actually measured, until a build "
                "in it is measured and flagged" % (build,))

    def test_the_h21_series_keeps_the_workaround(self):
        """Both builds actually run here, and the newer one arrived
        mid-session when Houdini updated."""
        for build in ((21, 0, 780), (21, 0, 790)):
            self.assertEqual(
                (882, 4), self._pick_with(build),
                "%s lost the workaround" % (build,))

    def test_the_origin_is_not_touched(self):
        """The scale is the whole workaround. If a y-flip ever creeps
        back in alongside it, the pick lands a viewport away - which is
        exactly what the previous attempt did, and it looked identical
        to the bug it was meant to fix."""
        for gl_y in (0, 2, 140, 277, 279):
            vp = _Viewport(h=self.HEIGHT, scale=self.SCALE)
            _Version(self, 21)
            # The OS is pinned for the same reason the BUILD is. This
            # test asserts the workaround FIRES, and the workaround is
            # macOS-only, so without the pin it reads the real host and
            # can only pass on a Mac - which is how it failed the first
            # time the suite was run on Windows, reporting "y=2 became
            # 2 - that is not a pure scale" for correct behaviour.
            _Platform(self, "macos")
            dragengine._pick(_Viewer(vp), "obj", 100, gl_y,
                             self.SCALE, self.HEIGHT)
            self.assertEqual(
                int(gl_y * self.SCALE), vp.asked[0][1],
                "y=%d became %d - that is not a pure scale"
                % (gl_y, vp.asked[0][1]))

    def test_a_display_without_scaling_is_untouched(self):
        """dpr 1.0: there is no missing factor to restore, so the
        workaround must not fire even on an affected build."""
        self.assertEqual((441, 2), self._pick_with(21, scale=1.0))

    def test_windows_never_gets_the_macos_workaround(self):
        """The bug SideFX fixed is scoped to macOS retina displays, but
        Windows reports scale factors too - 150% is its default on a
        4K laptop panel. Gating on the Houdini version alone applied
        this workaround there and broke picking on a viewport that
        never had the bug. That shipped, briefly."""
        self.assertEqual(
            (441, 2), self._pick_with(21, os_name="windows"),
            "a scaled Windows display got the macOS workaround")

    def test_linux_never_gets_it_either(self):
        self.assertEqual((441, 2), self._pick_with(21, os_name="linux"))

    def test_macos_at_the_same_scale_still_does(self):
        """Guards the guard: if the platform condition ever refuses
        everything, the two tests above pass while proving nothing."""
        self.assertEqual(
            (882, 4), self._pick_with(21, os_name="macos"),
            "the workaround no longer fires anywhere - the platform "
            "tests above are green for the wrong reason")


class TestViewportResolutionStillWorks(unittest.TestCase):

    def test_a_hit_is_reported_as_the_node_path(self):
        _Version(self, 21)
        # macOS, because the fake viewport only answers at (882, 4) -
        # the SCALED point. Off macOS the workaround does not fire, the
        # pick asks at (441, 2), and the miss comes back as "" - a
        # correct answer that reads here as a lost hit.
        _Platform(self, "macos")
        vp = _Viewport(hit=(882, 4))
        found = dragengine._pick(_Viewer(vp), "obj", 441, 2, 2.0, 279)
        self.assertEqual("/obj/sphere_object1", found)

    def test_a_miss_is_empty_not_an_exception(self):
        _Version(self, 21)
        vp = _Viewport(hit=None)
        self.assertEqual(
            "", dragengine._pick(_Viewer(vp), "obj", 10, 10, 2.0, 279))

    def test_a_raising_viewport_says_why_instead_of_going_quiet(self):
        """A bare `return ""` here is what made the original bug
        invisible: 'picked nothing' and 'the pick threw' were the same
        log line."""
        _Version(self, 21)

        class _Boom(_Viewport):
            def queryNodeAtPixel(self, x, y, **kwargs):
                raise hou.OperationFailed("no viewport")

        records = []
        real = dragengine._dbg
        self.addCleanup(setattr, dragengine, "_dbg", real)
        dragengine._dbg = lambda msg, **kw: records.append((msg, kw))

        self.assertEqual(
            "", dragengine._pick(_Viewer(_Boom()), "obj", 1, 1, 2.0, 279))
        self.assertTrue(
            any("raised" in m for m, _ in records),
            "the pick swallowed an exception without recording it: %s"
            % [m for m, _ in records])


if __name__ == "__main__":
    unittest.main()
