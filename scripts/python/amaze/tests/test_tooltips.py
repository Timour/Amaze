"""Every hover text lives in `tooltips.py`, so a rewording is one edit in one file. ▸p/messages-need-one-home"""

import ast
import os
import re
import unittest

from amaze import tooltips
from amaze.tests import test_support  # noqa: F401

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HOME = "tooltips.py"


def _sources():
    for root, dirs, files in os.walk(_PKG):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "tests")]
        for name in sorted(files):
            if name.endswith(".py") and name != HOME:
                yield os.path.join(root, name)


def _spelled_out(node):
    """The literals a call hands the helper, read through a conditional and through a format template; a computed string answers nothing."""
    if isinstance(node, ast.Constant):
        return [node.value] if isinstance(node.value, str) else []
    if isinstance(node, ast.IfExp):
        return _spelled_out(node.body) + _spelled_out(node.orelse)
    if isinstance(node, (ast.BoolOp, ast.JoinedStr)):
        return [t for part in node.values for t in _spelled_out(part)]
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mod, ast.Add)):
        return _spelled_out(node.left) + _spelled_out(node.right)
    return []    # a name, an attribute or a call - the words are not written here


def _offenders():
    """file:line and words for every hover text still spelled at its control."""
    found = []
    for path in _sources():
        with open(path, encoding="utf-8") as handle:
            try:
                tree = ast.parse(handle.read(), filename=path)
            except SyntaxError:
                continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) \
                else getattr(func, "id", "")
            if name not in ("tooltip_text", "setToolTip") or not node.args:   # setToolTip too: a raw literal there bypasses tooltip_text and escaped the first sweep
                continue
            for text in _spelled_out(node.args[0]):
                found.append("%s:%d  %r" % (
                    os.path.relpath(path, _PKG), node.lineno, text[:48]))
    return found


class NoControlSpellsItsOwnHoverText(unittest.TestCase):
    """A tooltip written at the control is a second home for words the design owns."""

    def test_no_hover_literal_survives_at_a_call_site(self):
        """The scan reads both arms of a conditional and leaves a computed string alone."""
        for source, expected in (
                ('w.setToolTip(ui_helpers.tooltip_text(\n'
                 '    "on" if live else "off"))\n', ["on", "off"]),
                ('ui_helpers.tooltip_text("\\n".join(bits))\n', [])):
            with self.subTest(planted=source):
                call = next(n for n in ast.walk(ast.parse(source))
                            if isinstance(n, ast.Call)
                            and isinstance(n.func, ast.Attribute)
                            and n.func.attr == "tooltip_text")
                self.assertEqual(expected, _spelled_out(call.args[0]))
        offenders = _offenders()
        self.assertEqual(
            [], offenders,
            "a control spells its own hover text instead of taking one "
            "from tooltips.py:\n  " + "\n  ".join(offenders))


class TheHoverTextsAreReadable(unittest.TestCase):

    def test_every_hover_text_is_a_string_with_words_in_it(self):
        names = [n for n in vars(tooltips) if n.isupper()]
        self.assertTrue(names, "tooltips.py holds no hover text at all")
        for name in sorted(names):
            text = getattr(tooltips, name)
            self.assertTrue(isinstance(text, str) and text.strip(),
                            name + " is not a hover text: %r" % (text,))

    def test_every_hover_text_the_code_names_exists(self):
        """A hover text renamed in `tooltips.py` but not where the code names it fails here."""
        missing = []
        for path in _sources():
            with open(path, encoding="utf-8") as handle:
                source = handle.read()
            for name in sorted(set(re.findall(r"\btooltips\.([A-Z][A-Z0-9_]*)\b", source))):
                if not hasattr(tooltips, name):
                    missing.append("%s: tooltips.%s" % (os.path.relpath(path, _PKG), name))
        self.assertEqual([], missing, "the code names hover texts tooltips.py does not have")
