"""The device pixel ratio is read FROM THE WIDGET, never app-wide. ▸r/screen-dpr"""

import ast
import os
import unittest

from amaze.tests import test_support  # noqa: F401


_SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

APP_WIDE = ("devicePixelRatio", "primaryScreen")   # both answer for the app, neither moves with the window ▸r/screen-dpr

EXEMPT = {
    ("helpers/ui_helpers.py", "_screen_dpr"),      # a tooltip is built before anyone knows which monitor it pops on
    ("utils/rc_calls.py", "describe"),    # records the value in the log, draws nothing
    ("helpers/theme.py", "screen_ratio"),          # the shared reader: primary is its documented no-widget fallback
}

IN_SCOPE = (
    "panel/notes_panel.py",
    "dialogs/prefs_dialog.py",
    "dialogs/icon_dialog.py",
    "helpers/theme.py",
    "helpers/ui_helpers.py",
)

REMAINING = set()                                 # app-wide reads still to fix; it may only shrink


def _scope_of(tree, line):
    """The nearest enclosing def/class name for a line, or '<module>'."""
    best = ("<module>", -1)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
            continue
        end = getattr(node, "end_lineno", node.lineno)
        if node.lineno <= line <= end and node.lineno > best[1]:
            best = (node.name, node.lineno)
    return best[0]


def _reads_in(source, relative):
    """[(scope, line, attr)] of app-wide ratio reads in `source`, EXEMPT removed."""
    tree = ast.parse(source, filename=relative)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in APP_WIDE:
            scope = _scope_of(tree, node.lineno)
            if (relative, scope) in EXEMPT:
                continue
            found.append((scope, node.lineno, node.attr))
    return sorted(found)


def _app_wide_reads(relative):
    """[(scope, line, attr)] for every app-wide ratio read in one file, EXEMPT removed."""
    path = os.path.join(_SRC, relative)
    with open(path, encoding="utf-8") as handle:
        return _reads_in(handle.read(), relative)


class TheRatioFollowsTheWindow(unittest.TestCase):

    def test_no_drawing_path_reads_an_app_wide_ratio(self):
        """The app ratio is the max over screens, the primary is one screen; neither follows the window."""
        live = set()
        for relative in IN_SCOPE:
            for scope, line, attr in _app_wide_reads(relative):
                live.add((relative, scope))
        added = sorted(live - REMAINING)
        self.assertEqual(
            [], added,
            "a NEW app-wide ratio read appeared: %s\n\nRead the WIDGET "
            "(`w.devicePixelRatioF()`), and read it where the pixmap is "
            "made. A deliberate primary-screen read goes in EXEMPT, with "
            "the reason." % added)
        fixed = sorted(REMAINING - live)
        self.assertEqual(
            [], fixed,
            "these are clean now - take them out of REMAINING so the "
            "ratchet cannot slip back: %s" % fixed)

    def test_the_scan_can_find_a_read(self):
        """A guard that matches nothing passes forever, so the scanner is fed a read it must see."""
        planted = ("class Widget:\n"
                   "    def paintEvent(self):\n"
                   "        r = QtGui.QGuiApplication.primaryScreen()\n")
        self.assertEqual(
            [("paintEvent", 3, "primaryScreen")],
            _reads_in(planted, "panel/planted.py"),
            "the scanner cannot see an app-wide read that is right in "
            "front of it, so its silence about the tree means nothing")


if __name__ == "__main__":
    unittest.main()
