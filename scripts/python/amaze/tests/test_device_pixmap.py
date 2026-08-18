"""The render-and-stamp contract: `ui_helpers.device_pixmap` rasterises at a ROUNDED `side * dpr` and stamps the ratio, and the sites that draw an SVG at device resolution go through it rather than hand-rolling the pair. Watch when calling: offscreen Qt invents one screen at dpr 1.0, so every ratio here is passed in rather than read from a screen, and `PENDING` names the sites not yet adopted."""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

import hou  # noqa: E402,F401

from amaze.helpers import ui_helpers  # noqa: E402
from amaze.tests import test_support  # noqa: E402,F401 - redirects the log

SQUARE = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
          '<rect width="10" height="10" fill="currentColor"/></svg>')

PENDING = ("panel/delegates.py:_badge_pixmap",)   # the one site still hand-rolling: adopting it opens delegates.py, whose 584-line comment cut cannot be banded and is hand work. Empty this tuple when it lands - the assertion is exact, so a stale entry reddens too. ROADMAP R30.7


def _svg(testcase):
    import tempfile
    folder = tempfile.mkdtemp()
    testcase.addCleanup(__import__("shutil").rmtree, folder,
                        ignore_errors=True)
    path = os.path.join(folder, "square.svg")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(SQUARE)
    return path


class ADevicePixmapIsRoundedAndStamped(unittest.TestCase):

    def test_a_whole_ratio_gives_side_times_ratio_device_pixels(self):
        pixmap = ui_helpers.device_pixmap(_svg(self), 18, 2.0)
        self.assertEqual(36, pixmap.width())
        self.assertEqual(2.0, pixmap.devicePixelRatio())

    def test_a_fractional_ratio_ROUNDS_it_does_not_truncate(self):
        """QPixmap truncates a float, so 13 x 1.5 = 19.5 would rasterise at 19 and the mark would go soft against a sharp thumbnail."""
        pixmap = ui_helpers.device_pixmap(_svg(self), 13, 1.5)
        self.assertEqual(20, pixmap.width())

    def test_a_half_point_side_rounds_up_too(self):
        pixmap = ui_helpers.device_pixmap(_svg(self), 17.5, 1.0)
        self.assertEqual(18, pixmap.width())

    def test_a_tiny_side_never_rasterises_to_nothing(self):
        """A 0-wide QPixmap is NULL, which paints as no icon at all."""
        pixmap = ui_helpers.device_pixmap(_svg(self), 1, 0.25)
        self.assertFalse(pixmap.isNull())
        self.assertEqual(1, pixmap.width())

    def test_the_logical_size_is_what_the_layout_sees(self):
        pixmap = ui_helpers.device_pixmap(_svg(self), 18, 2.0)
        self.assertEqual(18, pixmap.size().width() / pixmap.devicePixelRatio())


class TheFourSitesDrawThroughIt(unittest.TestCase):

    def test_no_site_hand_rolls_the_contract_any_more(self):
        """`setDevicePixelRatio` beside a `render_svg_pixmap` is the shape this helper replaced; `device_pixmap` is the ONE home and is exempt by name, and `PENDING` carries the sites not yet adopted."""
        import ast
        import re
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        offenders = []
        for folder, _dirs, files in os.walk(root):
            if os.path.basename(folder) == "tests":
                continue
            for name in sorted(files):
                if not name.endswith(".py"):
                    continue
                path = os.path.join(folder, name)
                with open(path, "r", encoding="utf-8") as handle:
                    text = handle.read()
                tree = ast.parse(text)
                for scope in ast.walk(tree):
                    if not isinstance(scope, (ast.FunctionDef,
                                              ast.AsyncFunctionDef)):
                        continue
                    if scope.name == "device_pixmap":
                        continue
                    body = ast.get_source_segment(text, scope) or ""
                    if ("render_svg_pixmap(" in body
                            and "setDevicePixelRatio" in body):
                        offenders.append("%s:%s" % (
                            test_support.posix_relpath(path, root),
                            scope.name))
        self.assertEqual(
            sorted(PENDING), sorted(offenders),
            "the hand-rolled set moved: a NEW site rasterises and stamps "
            "by hand, or a PENDING one was adopted and not removed from "
            "the tuple")
        self.assertTrue(
            re.search(r"def device_pixmap", open(os.path.join(
                root, "helpers", "ui_helpers.py"),
                encoding="utf-8").read()),
            "the scan exempts a helper that no longer exists")

    def test_a_missing_badge_is_a_NULL_pixmap_not_a_blank_square(self):
        from amaze.panel import delegates
        delegates.AssetItemDelegate._badge_cache.clear()
        self.addCleanup(delegates.AssetItemDelegate._badge_cache.clear)
        pixmap = delegates.AssetItemDelegate._badge_pixmap(
            "no_such_badge_asset", 18, 2.0)
        self.assertTrue(
            pixmap.isNull(),
            "a missing badge came back as a sized transparent pixmap, "
            "which paints over the thumbnail instead of skipping")

    def test_the_glyph_cache_still_hands_back_its_own_object(self):
        from amaze.panel import notes_panel
        notes_panel._glyph_cache.clear()
        self.addCleanup(notes_panel._glyph_cache.clear)
        first = notes_panel._feather_icon("plus-circle", 18, "#ffffff")
        again = notes_panel._feather_icon("plus-circle", 18, "#ffffff")
        self.assertIs(first, again,
                      "the glyph cache re-parsed the SVG for a repaint")


if __name__ == "__main__":
    unittest.main()
