"""The viewport pick's coordinate space, per Houdini build: queryNodeAtPixel does not apply the device pixel ratio before 22.0.391 (SideFX's changelog scopes the breakage to macOS retina displays), so those builds want the point already multiplied by it - same origin and convention as 22.0.393, one factor apart. Two lessons ride with the behaviour: ONE PROBE SAMPLE IS NOT AN ANSWER, since an earlier single record put the cursor near a corner rather than on the sphere and a candidate hitting looks identical to a candidate being right; and A VIEWPORT REPORTS DEVICE PIXELS WHILE QT REPORTS LOGICAL ONES, which the stubs below model, because a stub reporting logical sizes agrees with the bug instead of catching it."""

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
    """One viewport that records the pixel it was asked about, reporting its size the way Houdini does - FOUR values in DEVICE pixels, a 481x279 widget at dpr 2.0 giving (0, 0, 962, 558) - because a stub reporting logical values carries the same assumption that produced the bug."""

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
    """Pin hou.applicationVersion for the duration of a test - real builds, because the gate keys on the build number: 21.0.780 measured, 22.0.393 working, 22.0.390 the build immediately before the Retina picking fix."""

    BUILDS = {21: (21, 0, 780), 22: (22, 0, 393)}

    def __init__(self, testcase, major):
        self.major = major
        version = self.BUILDS.get(major, (major, 0, 0)) \
            if not isinstance(major, tuple) else major
        real = hou.applicationVersion
        testcase.addCleanup(setattr, hou, "applicationVersion", real)
        hou.applicationVersion = lambda: version


class _Platform:
    """Pin the OS for the duration of a test - the workaround is macOS-only, matching the scope of the vendor changelog, and Windows reports scale factors too (150% being its common default), so without a platform condition the workaround fires there and breaks picking on a viewport that never had the bug."""

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

    def test_the_whole_h22_series_behaves_like_the_h22_we_measured(self):
        """The breakpoint sits at 22.0.0, NOT at the changelog's 22.0.391 - asserting otherwise was an INFERENCE from the changelog written down as a measurement, and no 22.0.x below 393 has ever run here; the asymmetry is the argument, since leaving a host bug unworked-around on an untested build costs a bug the user would have had anyway, while applying an untested workaround to a build that works breaks something that was fine."""
        for build in ((22, 0, 0), (22, 0, 390), (22, 0, 391),
                      (22, 0, 393), (22, 0, 394)):
            self.assertEqual(
                (441, 2), self._pick_with(build),
                "%s got the workaround - the H22 series must behave "
                "like the H22 that was actually measured, until a build "
                "in it is measured and flagged" % (build,))
        for build in ((21, 0, 780), (21, 0, 790)):    # both measured: H21 wants device pixels
            self.assertEqual(
                (882, 4), self._pick_with(build),
                "%s lost the workaround - it does not apply the device "
                "pixel ratio itself" % (build,))

    def test_the_origin_is_not_touched(self):
        """The scale is the whole workaround: a y-flip creeping back in alongside it puts the pick a viewport away, which is what the previous attempt did and it looked identical to the bug it was meant to fix."""
        for gl_y in (0, 2, 140, 277, 279):
            vp = _Viewport(h=self.HEIGHT, scale=self.SCALE)
            _Version(self, 21)
            _Platform(self, "macos")  # the OS is pinned for the same reason the BUILD is: this asserts the workaround FIRES, and it is macOS-only, so without the pin the test reads the real host and can only pass on a Mac - which is how it failed on its first Windows run
            dragengine._pick(_Viewer(vp), "obj", 100, gl_y,
                             self.SCALE, self.HEIGHT)
            self.assertEqual(
                int(gl_y * self.SCALE), vp.asked[0][1],
                "y=%d became %d - that is not a pure scale"
                % (gl_y, vp.asked[0][1]))

    def test_a_display_without_scaling_is_untouched(self):
        """dpr 1.0: no missing factor to restore, so the workaround must not fire even on an affected build."""
        self.assertEqual((441, 2), self._pick_with(21, scale=1.0))

    def test_windows_never_gets_the_macos_workaround(self):
        """The vendor bug is scoped to macOS retina displays while Windows reports scale factors too (150% on a 4K laptop panel), so gating on the Houdini version alone applied the workaround there and broke picking on a viewport that never had the bug - and that shipped, briefly."""
        for os_name in ("windows", "linux"):
            self.assertEqual(
                (441, 2), self._pick_with(21, os_name=os_name),
                "a scaled %s display got the macOS workaround" % os_name)


class TestViewportResolutionStillWorks(unittest.TestCase):

    def test_a_hit_is_reported_as_the_node_path(self):
        _Version(self, 21)
        _Platform(self, "macos")  # macOS, because the fake viewport only answers at the SCALED point (882, 4): elsewhere the workaround does not fire, the pick asks at (441, 2), and the correct miss reads here as a lost hit
        vp = _Viewport(hit=(882, 4))
        found = dragengine._pick(_Viewer(vp), "obj", 441, 2, 2.0, 279)
        self.assertEqual("/obj/sphere_object1", found)
        vp = _Viewport(hit=None)
        self.assertEqual(
            "", dragengine._pick(_Viewer(vp), "obj", 10, 10, 2.0, 279),
            "a miss is not an empty answer")

    def test_a_raising_viewport_says_why_instead_of_going_quiet(self):
        """A bare `return ""` here made the original bug invisible - a miss and a raised exception produced the same log line."""
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


class TheCursorIsReadOnlyForARecord(unittest.TestCase):
    """`_cursor_truth` feeds only the pick record, so a pick with the debug log off never reads it."""

    class _Seen(_Viewer):
        def qtWindow(self):
            window = QtWidgets.QWidget()
            window.resize(481, 279)
            return window

        def locateSceneGraphPrim(self, x, y):
            return (-1, "")

    def _picked(self, log_on):
        """[(world, record data)] for one obj and one lop pick; counts `_cursor_truth` reads."""
        from unittest import mock
        _Version(self, 21)
        vp = _Viewport()
        vp.resolutionInPixels = lambda: (962, 558)
        reads, records = [], []
        real = dragengine._cursor_truth

        def counting(viewer):
            reads.append(viewer)
            return real(viewer)

        dragengine.begin("material")
        with mock.patch.object(dragengine, "_cursor_truth", counting), \
                mock.patch.object(dragengine, "_dbg_on", return_value=log_on), \
                mock.patch.object(dragengine, "_dbg",
                                  lambda msg, **kw: records.append(kw)):
            for world in ("obj", "lop"):
                dragengine._pick(self._Seen(vp), world, 10, 10, 2.0, 279)
        return reads, records

    def test_a_pick_with_the_log_off_reads_no_cursor(self):
        reads, records = self._picked(False)
        self.assertEqual([], records, "premise: nothing is recorded")
        self.assertEqual(0, len(reads),
                         "the pick read the cursor for a record it never wrote")
        reads, records = self._picked(True)
        self.assertEqual(2, len(reads))
        self.assertEqual(["obj", "lop"], [r["world"] for r in records])
        for record in records:
            self.assertEqual((481, 279), record["widget"])
            self.assertEqual((962, 558), record["resolution"])


if __name__ == "__main__":
    unittest.main()
