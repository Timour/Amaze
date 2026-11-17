"""Every hover text is in `tooltips.py`, so a rewording is one edit. ▸p/messages-in-three-places"""

import ast
import os
import re
import unittest

from amaze import tooltips
from amaze.tests import test_support  # noqa: F401

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TOOLTIPS_FILE = "tooltips.py"


def _sources():
    for root, dirs, files in os.walk(_PKG):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "tests")]
        for name in sorted(files):
            if name.endswith(".py") and name != TOOLTIPS_FILE:
                yield os.path.join(root, name)


def _string_literals(node):
    """The string literals in a call argument, including conditionals and format templates."""
    if isinstance(node, ast.Constant):
        return [node.value] if isinstance(node.value, str) else []
    if isinstance(node, ast.IfExp):
        return _string_literals(node.body) + _string_literals(node.orelse)
    if isinstance(node, (ast.BoolOp, ast.JoinedStr)):
        return [t for part in node.values for t in _string_literals(part)]
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mod, ast.Add)):
        return _string_literals(node.left) + _string_literals(node.right)
    return []    # a name, an attribute or a call - the text is not a literal in this call


def _offenders():
    """`file:line` and text of every literal passed to `setToolTip` or `tooltip_text`."""
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
            if name not in ("tooltip_text", "setToolTip") or not node.args:   # setToolTip too: a raw literal there bypasses tooltip_text
                continue
            for text in _string_literals(node.args[0]):
                found.append("%s:%d  %r" % (
                    os.path.relpath(path, _PKG), node.lineno, text[:48]))
    return found


class NoControlDefinesItsOwnHoverText(unittest.TestCase):
    """A tooltip literal in widget code is a second copy of text that belongs in `tooltips.py`."""

    def test_no_hover_text_literal_is_left_at_a_call_site(self):
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
                self.assertEqual(expected, _string_literals(call.args[0]))
        offenders = _offenders()
        self.assertEqual(
            [], offenders,
            "a widget passes a tooltip literal instead of a name "
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
