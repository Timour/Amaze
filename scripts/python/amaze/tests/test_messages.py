"""Every dialog message lives in `messages.py`, and its placeholders match what its callers pass. ▸p/messages-need-one-home"""
import ast
import os
import re
import unittest

from amaze import messages
from amaze.tests import test_support  # noqa: F401

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DIALOG_CALLS = {"displayMessage", "alert"}

PLACEHOLDER = re.compile(r"%[sdif]")


def _sources():
    for root, dirs, files in os.walk(_PKG):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "tests")]
        for name in sorted(files):
            if name.endswith(".py") and name != "messages.py":
                yield os.path.join(root, name)


def _constants():
    return {k: v for k, v in vars(messages).items()
            if k.isupper() and isinstance(v, str)}


def _literal_words(arg) -> str:
    """The longest literal in a message argument: plain, before `%`, beside `+`, or in an f-string."""
    if isinstance(arg, ast.Constant):
        return arg.value if isinstance(arg.value, str) else ""
    if isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Mod):
        return _literal_words(arg.left)
    if isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Add):
        return max(_literal_words(arg.left), _literal_words(arg.right), key=len)
    if isinstance(arg, ast.JoinedStr):
        return "".join(part.value for part in arg.values
                       if isinstance(part, ast.Constant))
    return ""


def _spelled_messages(tree) -> list:
    """[(line, words)] for each dialog call in `tree` whose message carries its own words."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in DIALOG_CALLS:
            continue
        words = _literal_words(node.args[0])
        if len(words) > 8:
            found.append((node.lineno, words))
    return found


class NoDialogSpellsItsOwnMessage(unittest.TestCase):
    """A message written at the call site is a second home for words the design owns, and the one place a Figma edit cannot reach."""

    def test_no_message_literal_survives_at_a_call_site(self):
        offenders = []
        for path in _sources():
            with open(path, encoding="utf-8") as handle:
                try:
                    tree = ast.parse(handle.read(), filename=path)
                except SyntaxError:
                    continue
            for line, words in _spelled_messages(tree):
                offenders.append("%s:%d  %r" % (
                    os.path.relpath(path, _PKG), line, words[:48]))
        self.assertEqual(
            [], offenders,
            "a dialog spells its own message instead of taking one from "
            "messages.py - a Figma edit can never reach it:\n  "
            + "\n  ".join(offenders))

    def test_the_scan_can_see_a_literal(self):
        """A scanner matching nothing passes forever."""
        for shape in ('ui.displayMessage("a sentence long enough")',
                      'ui.displayMessage("a sentence long enough %s" % x)',
                      'ui.displayMessage("a sentence long enough:\\n" + x)',
                      'ui.displayMessage(x + "a sentence long enough")',
                      'ui.displayMessage(f"a sentence {x} long enough")'):
            with self.subTest(shape=shape):
                self.assertEqual(1, len(_spelled_messages(ast.parse(shape))))
        tree = ast.parse('ui.displayMessage(messages.X % "\\n".join(x))')
        self.assertEqual([], _spelled_messages(tree),
                         "a message taken from the register was flagged")


class ThePlaceholdersAgreeWithTheCallers(unittest.TestCase):
    """Editing wording in one file is easy; editing OUT a `%s` a caller still supplies raises `TypeError` in front of the user, and only on the branch that shows it."""

    def _formatted(self):
        """{constant name: how many args the callers pass}, from `X % (...)`."""
        used = {}
        for path in _sources():
            with open(path, encoding="utf-8") as handle:
                try:
                    tree = ast.parse(handle.read(), filename=path)
                except SyntaxError:
                    continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.BinOp) \
                        or not isinstance(node.op, ast.Mod):
                    continue
                left = node.left
                if not isinstance(left, ast.Attribute) \
                        or not isinstance(left.value, ast.Name) \
                        or left.value.id != "messages":
                    continue
                right = node.right
                count = len(right.elts) if isinstance(right, ast.Tuple) else 1
                used.setdefault(left.attr, set()).add(
                    (count, os.path.relpath(path, _PKG), node.lineno))
        return used

    def test_every_formatted_message_has_the_placeholders_its_caller_fills(self):
        constants = _constants()
        offenders = []
        for name, uses in sorted(self._formatted().items()):
            text = constants.get(name)
            if text is None:
                offenders.append("%s is formatted but is not in messages.py"
                                 % name)
                continue
            want = len(PLACEHOLDER.findall(text))
            for count, path, line in sorted(uses):
                if count != want:
                    offenders.append(
                        "%s carries %d placeholder(s) but %s:%d passes %d"
                        % (name, want, path, line, count))
        self.assertEqual(
            [], offenders,
            "a message and its caller disagree about placeholders - this "
            "raises TypeError in front of the user:\n  "
            + "\n  ".join(offenders))

    def test_an_unformatted_message_carries_no_placeholder(self):
        """The other direction: a `%s` left in a message nobody formats prints raw to the user."""
        constants = _constants()
        formatted = set(self._formatted())
        referenced, offenders = set(), []
        for path in _sources():
            with open(path, encoding="utf-8") as handle:
                body = handle.read()
            for name in constants:
                if "messages." + name in body:
                    referenced.add(name)
        for name in sorted(referenced - formatted):
            found = PLACEHOLDER.findall(constants[name])
            if found:
                offenders.append("%s carries %s and is never formatted"
                                 % (name, ", ".join(found)))
        self.assertEqual(
            [], offenders,
            "a placeholder would print raw to the user:\n  "
            + "\n  ".join(offenders))


class TheCleanLibraryConfirmSaysWhereFilesGo(unittest.TestCase):
    """Clean moves a file nothing uses into the holding folder; it does not delete it."""

    def test_the_confirm_names_how_long_the_holding_folder_keeps_them(self):
        from amaze.core import quarantine
        self.assertIn(
            "%d days" % quarantine.QUARANTINE_DAYS,
            messages.HELP_CLEAN_LIBRARY,
            "the Clean Library confirmation does not say files are kept "
            "in the holding folder, so it reads as a permanent delete")
