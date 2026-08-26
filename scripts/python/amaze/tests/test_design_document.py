"""The design lives in ONE document: no second home for a colour, a dialog size or a drawn word. ▸p/one-design-document"""
import ast
import os
import re
import unittest

from amaze import amazetheme
from amaze.panel import empty_state, sections

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HEX = re.compile(r'"#[0-9a-fA-F]{3,8}"')

DRAWS_CHROME = (    # the files that paint the panel and its dialogs; a colour here is a DESIGN colour and belongs in the one document
    "helpers/ui_helpers.py",
    "panel/panel.py",
    "panel/delegates.py",
    "panel/notes_panel.py",
    "panel/empty_state.py",
    "dialogs/base_dialog.py",
    "dialogs/icon_dialog.py",
    "dialogs/save_dialog.py",
    "dialogs/gradient_dialog.py",
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
            continue        # a hex QUOTED in a comment explains, it does not paint
        code = line.split("    # ")[0]
        for hit in HEX.findall(code):
            found.append((number, hit, line.strip()))
    return found


class NoSecondHomeForAColour(unittest.TestCase):

    def test_the_chrome_files_carry_no_literal_hex(self):
        offenders = []
        for relative in DRAWS_CHROME:
            path = os.path.join(_ROOT, relative)
            if not os.path.exists(path):
                continue
            for number, hit, line in _literal_hexes(path):
                if any(needle in line
                       for needle, _why in ALLOWED.get(relative, ())):
                    continue
                offenders.append("%s:%d  %s" % (relative, number, hit))
        self.assertEqual(
            [], offenders,
            "a design colour was written where it is drawn instead of "
            "in amazetheme.py - one document, so a Figma change is one "
            "edit:\n  " + "\n  ".join(offenders))

    def test_the_document_can_see_a_hex_at_all(self):
        """A scanner that matches nothing passes forever."""
        with open(os.path.join(_ROOT, "amazetheme.py"),
                  encoding="utf-8") as handle:
            body = handle.read()
        self.assertTrue(
            HEX.findall(body),
            "the scanner finds no hex even in the design document, so "
            "it cannot fail when one is added elsewhere")

    def test_every_scanned_file_is_really_there(self):
        """A path that no longer resolves is skipped silently, so the list would rot into a scan of nothing."""
        for relative in DRAWS_CHROME:
            with self.subTest(file=relative):
                self.assertTrue(
                    os.path.exists(os.path.join(_ROOT, relative)),
                    "%s is listed as a chrome file and does not exist"
                    % relative)


SIZERS = ("setFixedWidth", "setMinimumWidth", "setMaximumWidth",
          "setFixedSize", "setMinimumSize", "setBaseSize")

DIALOG_DIR = os.path.join(_ROOT, "dialogs")


class NoDialogSetsItsOwnWidth(unittest.TestCase):
    """A width every dialog reads from ONE place fails the SAME way in all of them; four dialogs rendering four different widths is proof the constant never reached any of them. So the width is the shell's to apply and no dialog may set its own. ▸p/shared-means-it-fails-together"""

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

    def test_only_the_shared_shell_sizes_a_dialog(self):
        offenders = []
        for name in sorted(os.listdir(DIALOG_DIR)):
            if not name.endswith(".py") or name == "base_dialog.py":
                continue        # the shell is the ONE place a width is applied
            for line, call in self._self_sizing_calls(
                    os.path.join(DIALOG_DIR, name)):
                offenders.append("dialogs/%s:%d  self.%s(...)"
                                 % (name, line, call))
        self.assertEqual(
            [], offenders,
            "a dialog sizes ITSELF instead of declaring FORM_WIDTH and "
            "letting the shell apply it - that is how four dialogs came "
            "to render four different widths:\n  "
            + "\n  ".join(offenders))

    def test_the_scan_can_see_a_self_sizing_call(self):
        """A scanner that matches nothing passes forever."""
        tree = ast.parse("class D:\n"
                         "    def f(self):\n"
                         "        self.setFixedWidth(350)\n")
        hits = [n for n in ast.walk(tree)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr in SIZERS
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id == "self"]
        self.assertEqual(1, len(hits),
                         "the scanner cannot see a self-sizing call even "
                         "in a sample written to contain one")

    def test_every_dialog_width_is_a_named_constant(self):
        """A FORM_WIDTH assigned a bare number is a second home for a size, however few characters it is."""
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


class TheDrawnWordsComeFromTheDocument(unittest.TestCase):

    def test_every_blank_reads_its_words_from_it(self):
        self.assertIs(amazetheme.EMPTY_SHARED, empty_state.SHARED,
                      "the shared blanks grew a second copy of their "
                      "words")
        for key, cls, expected in (
                ("material", sections.MaterialSection,
                 amazetheme.EMPTY_MATERIAL),
                ("gradient", sections.GradientSection,
                 amazetheme.EMPTY_COLOR),
                ("cop", sections.CopSection, amazetheme.EMPTY_NODE),
                ("code", sections.CodeSection, amazetheme.EMPTY_CODE),
                ("file", sections.FileSection, amazetheme.EMPTY_FILE)):
            with self.subTest(section=key):
                self.assertIs(expected, cls.EMPTY,
                              "%s spells its first-run blank itself" % key)

    def test_a_button_label_is_named_once(self):
        """Two constants holding the same words is the drift this file exists to stop."""
        labels = {name: value for name, value in vars(amazetheme).items()
                  if name.startswith(("BTN_", "LABEL_", "TITLE_"))}
        seen = {}
        for name, value in sorted(labels.items()):
            self.assertNotIn(
                value, seen,
                "%s and %s are both %r - one of them is the drift"
                % (seen.get(value), name, value))
            seen[value] = name
