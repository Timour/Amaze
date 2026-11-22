"""Colours, dialog sizes and empty texts are set only in amazetheme.py ▸p/one-design-document"""
import ast
import os
import re
import unittest

from amaze import amazetheme
from amaze.panel import empty_state
from amaze.tests import test_support  # noqa: F401

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HEX = re.compile(r'"#[0-9a-fA-F]{3,8}"')

DRAWS_CHROME = (    # files that draw the panel and dialogs; their colours belong in amazetheme.py
    "helpers/ui_helpers.py",
    "panel/panel.py",
    "panel/delegates.py",
    "panel/notes_panel.py",
    "panel/info_panel.py",
    "panel/empty_state.py",
    "dialogs/base_dialog.py",
    "dialogs/icon_dialog.py",
    "dialogs/save_dialog.py",
    "dialogs/gradient_dialog.py",
    "dialogs/library_dialog.py",
)

ALLOWED = {    # a literal that is NOT a design colour: {file: (needle, why)}
    "panel/notes_panel.py": (
        ("#3", "an alpha-blend step computed per to-do row"),),
}


def _literal_hexes(path):
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    found = []
    for number, line in enumerate(source.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue        # a hex in a comment is not a colour the code uses
        code = line.split("    # ")[0]
        for hit in HEX.findall(code):
            found.append((number, hit, line.strip()))
    return found


class ColoursAreDefinedOnlyInAmazetheme(unittest.TestCase):

    def test_the_chrome_files_contain_no_literal_hex(self):
        offenders = []
        for relative in DRAWS_CHROME:
            path = os.path.join(_ROOT, relative)
            self.assertTrue(os.path.exists(path),
                            "%s is listed as a chrome file and does not exist"
                            % relative)
            for number, hit, line in _literal_hexes(path):
                if any(needle in line
                       for needle, _why in ALLOWED.get(relative, ())):
                    continue
                offenders.append("%s:%d  %s" % (relative, number, hit))
        self.assertEqual(
            [], offenders,
            "a design colour was written where it is drawn instead of "
            "in amazetheme.py - one file, so a Figma change is one "
            "edit:\n  " + "\n  ".join(offenders))

    def test_the_hex_scan_finds_a_hex_in_amazetheme(self):
        """A scan that matches nothing always passes."""
        with open(os.path.join(_ROOT, "amazetheme.py"),
                  encoding="utf-8") as handle:
            body = handle.read()
        self.assertTrue(
            HEX.findall(body),
            "the scanner finds no hex even in amazetheme.py, so "
            "it cannot fail when one is added elsewhere")


SIZERS =("setFixedWidth", "setMinimumWidth", "setMaximumWidth",
          "setFixedSize", "setMinimumSize", "setBaseSize")

GEOMETRY = ("resize", "setGeometry")
SELF_READERS = ("width", "height", "size", "geometry", "rect",
                "frameGeometry")

DIALOG_DIR = os.path.join(_ROOT, "dialogs")


class NoDialogSetsItsOwnWidth(unittest.TestCase):
    """No dialog sets its own width; base_dialog.py does ▸p/shared-means-it-fails-together"""

    def _self_sizing_calls(self, path):
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        found = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if func.attr not in SIZERS:
                continue
            if isinstance(func.value, ast.Name) and func.value.id == "self":
                found.append((node.lineno, func.attr))
        return found

    def _geometry_from_itself(self, path):
        """`self.resize(self.width(), ...)` - a geometry call whose own arguments read the widget back."""
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        found = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or \
                    func.attr not in GEOMETRY:
                continue
            if not (isinstance(func.value, ast.Name)
                    and func.value.id == "self"):
                continue
            for arg in ast.walk(ast.Module(body=list(node.args),
                                           type_ignores=[])):
                if not isinstance(arg, ast.Call):
                    continue
                inner = arg.func
                if isinstance(inner, ast.Attribute) \
                        and inner.attr in SELF_READERS \
                        and isinstance(inner.value, ast.Name) \
                        and inner.value.id == "self":
                    found.append((node.lineno, func.attr, inner.attr))
        return found

    def test_only_the_shared_shell_sizes_a_dialog(self):
        offenders = []
        for name in sorted(os.listdir(DIALOG_DIR)):
            if not name.endswith(".py") or name == "base_dialog.py":
                continue        # base_dialog.py is the only file that applies a width
            for line, call in self._self_sizing_calls(
                    os.path.join(DIALOG_DIR, name)):
                offenders.append("dialogs/%s:%d  self.%s(...)"
                                 % (name, line, call))
        self.assertEqual(
            [], offenders,
            "a dialog sizes ITSELF instead of declaring FORM_WIDTH and "
            "letting base_dialog.py apply it - that is how four dialogs came "
            "to render four different widths:\n  "
            + "\n  ".join(offenders))

    def test_no_dialog_sizes_itself_from_its_own_geometry(self):
        """No geometry call reads the widget's size; the layout gives `sizeHint` ▸p/sized-from-640x480"""
        offenders = []
        for name in sorted(os.listdir(DIALOG_DIR)):
            if not name.endswith(".py"):
                continue
            for line, call, read in self._geometry_from_itself(
                    os.path.join(DIALOG_DIR, name)):
                offenders.append("dialogs/%s:%d  self.%s(... self.%s() ...)"
                                 % (name, line, call, read))
        self.assertEqual(
            [], offenders,
            "a dialog sizes itself from its own geometry. Before the "
            "first show() that is Qt's 640x480 default, not a size from the "
            "layout or amazetheme - which is why Preferences was drawn "
            "at 640 while amazetheme.py gave 480:\n  "
            + "\n  ".join(offenders))

    def test_the_geometry_scan_can_see_one(self):
        """The scan that found nothing must find a planted one."""
        import tempfile
        for scan, body, found in (
                (self._geometry_from_itself,
                 "        self.resize(self.width(), 10)\n",
                 [(3, "resize", "width")]),
                (self._geometry_from_itself,    # an amazetheme width and a sizeHint pass
                 "        self.resize(theme.ui_px(A.W),\n"
                 "                    self.sizeHint().height())\n", []),
                (self._self_sizing_calls,
                 "        self.setFixedWidth(350)\n", [(3, "setFixedWidth")])):
            with self.subTest(body=body.strip()):
                with tempfile.TemporaryDirectory() as folder:
                    path = os.path.join(folder, "d.py")
                    with open(path, "w", encoding="utf-8") as handle:
                        handle.write("class D:\n    def f(self):\n" + body)
                    self.assertEqual(
                        found, scan(path),
                        "the scanner misreads a sample written to test it")

    def test_every_dialog_width_is_a_named_constant(self):
        """A FORM_WIDTH assigned a bare number defines a size outside amazetheme.py."""
        offenders = []
        for name in sorted(os.listdir(DIALOG_DIR)):
            if not name.endswith(".py"):
                continue
            path = os.path.join(DIALOG_DIR, name)
            with open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assign):
                    continue
                names = [t.id for t in node.targets
                         if isinstance(t, ast.Name)]
                if not any(n in ("FORM_WIDTH", "FIELD_WIDTH")
                           for n in names):
                    continue
                if isinstance(node.value, ast.Constant) and \
                        node.value.value is not None:
                    offenders.append(
                        "dialogs/%s:%d  %s = %r"
                        % (name, node.lineno, names[0], node.value.value))
        self.assertEqual(
            [], offenders,
            "a dialog width is written as a bare number instead of a "
            "name from amazetheme.py:\n  " + "\n  ".join(offenders))


class TheNamedFrameSizesAreTheDrawnFrames(unittest.TestCase):
    """Each named size equals the `DIALOG_LAYOUT` frame size of every frame that uses it."""

    def test_each_named_size_is_every_family_frame(self):
        layout = amazetheme.DIALOG_LAYOUT
        for frames, name, want in (
                (("D01",), "D01_FRAME", amazetheme.D01_FRAME),
                (("D02",), "D02 opening size",
                 (amazetheme.D02_FORM_WIDTH, amazetheme.D02_FRAME_H)),
                (("D09", "D13"), "SAVE_WIDTH", amazetheme.SAVE_WIDTH),
                (("D15",), "D15_WIDTH", amazetheme.D15_WIDTH),
                (("D11",), "D11_FORM_WIDTH", amazetheme.D11_FORM_WIDTH)):
            for frame in frames:
                drawn = layout[frame]["frame"]
                with self.subTest(frame=frame, name=name):
                    self.assertEqual(drawn if isinstance(want, tuple) else drawn[0],
                                     want, "%s is not %s's drawn size" % (name, frame))


class TheDrawnWordsComeFromTheDocument(unittest.TestCase):

    def test_the_empty_state_texts_are_the_ones_in_amazetheme(self):
        self.assertIs(amazetheme.EMPTY_SHARED, empty_state.SHARED,
                      "the shared empty-state texts have a second copy "
                      "in empty_state.py")
        self.assertEqual(
            {empty_state.NO_MATCH, empty_state.NO_FAVOURITES,
             empty_state.UNREACHABLE}, set(amazetheme.EMPTY_SHARED),
            "the shared empty-state texts are not the three drawn - an empty "
            "category shows its grid, never a text")

    def test_a_button_label_is_named_once(self):
        """Two constants holding the same label can come to differ: each label is defined once."""
        labels = {name: value for name, value in vars(amazetheme).items()
                  if name.startswith(("BTN_", "LABEL_", "TITLE_"))}
        seen = {}
        for name, value in sorted(labels.items()):
            self.assertNotIn(
                value, seen,
                "%s and %s are both %r - one of them should go"
                % (seen.get(value), name, value))
            seen[value] = name
