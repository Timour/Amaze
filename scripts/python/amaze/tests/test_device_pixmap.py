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

PENDING = ()   # every site draws through the helper; the assertion is EXACT both ways, so a new hand-rolled site reddens and so does a stale entry here


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

    def test_the_device_width_is_side_times_ratio_rounded_never_zero(self):
        """QPixmap truncates a float (19.5 rasterises at 19) and a 0-wide pixmap paints nothing."""
        svg = _svg(self)
        for side, ratio, device in ((18, 2.0, 36), (13, 1.5, 20), (17.5, 1.0, 18), (1, 0.25, 1)):
            with self.subTest(side=side, ratio=ratio):
                pixmap = ui_helpers.device_pixmap(svg, side, ratio)
                self.assertFalse(pixmap.isNull())
                self.assertEqual(device, pixmap.width())
                self.assertEqual(ratio, pixmap.devicePixelRatio())
        pixmap = ui_helpers.device_pixmap(svg, 18, 2.0)
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
