"""Every dialog message lives in `messages.py`, and its placeholders match what its callers pass. ▸p/messages-need-one-home"""
import ast
import os
import re
import unittest

from amaze import messages
from amaze.tests import test_support  # noqa: F401

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HOU_DIALOGS = {"displayMessage", "displayConfirmation", "displayCustomConfirmation",
               "selectFromList", "readInput", "readMultiInput"}
TEXT_KEYWORDS = {"text", "help", "buttons", "title", "message", "details", "details_label",
                 "column_header"}
SINKS = {"alert", "refuse", "status", "note"}    # read as `debug.<sink>(sentence)`
BOX_STATICS = {"information", "warning", "critical", "question", "about"}
BOX_SETTERS = {"setText", "setInformativeText", "setDetailedText", "setWindowTitle", "addButton"}
WRAPPERS = {"str", "tuple", "list", "sorted", "Damage"}    # hand their argument's words through
INTERFACE = ("panel", "dialogs", "utils")    # text followed past the call, and notes read, only here

PLACEHOLDER = re.compile(r"%[sdif]")
FIELD = re.compile(r"%[-+ #0-9.]*[sdifr%]")
A_WORD = re.compile(r"[A-Za-z]{3,}")
DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _sources():
    for root, dirs, files in os.walk(_PKG):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "tests")]
        for name in sorted(files):
            if name.endswith(".py") and name != "messages.py":
                yield os.path.join(root, name)


def _constants():
    return {k: v for k, v in vars(messages).items()
            if k.isupper() and isinstance(v, str)}


def _worded(text) -> bool:
    """A literal a reader takes for wording: a word of three letters once its `%` fields are out."""
    return isinstance(text, str) and bool(A_WORD.search(FIELD.sub("", text)))


def _own(root):
    """Every node of `root`'s own body; a nested def or class is a scope of its own."""
    stack = list(ast.iter_child_nodes(root))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, DEFS + (ast.ClassDef,)):
            stack.extend(ast.iter_child_nodes(node))


def _bindings(root) -> dict:
    """{name: [value]} bound in `root`'s body by `=`, `+=`, a loop, `append`, `extend` or `insert`."""
    found = {}

    def bind(target, value):
        if isinstance(target, ast.Name):
            found.setdefault(target.id, []).append(value)
        elif isinstance(target, (ast.Tuple, ast.List)):
            paired = (isinstance(value, (ast.Tuple, ast.List))
                      and len(value.elts) == len(target.elts))
            for at, element in enumerate(target.elts):
                bind(element, value.elts[at] if paired
                     else ast.Subscript(value=value, slice=ast.Constant(at)))

    for node in _own(root):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                bind(target, node.value)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)) and node.value is not None:
            bind(node.target, node.value)
        elif isinstance(node, ast.For):
            bind(node.target, node.iter)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr in ("append", "extend", "insert")
              and isinstance(node.func.value, ast.Name) and node.args):
            bind(node.func.value, node.args[-1])
    return found


def _callee(node):
    """The name a call reaches inside its own module - `f(...)`, `self.f(...)`, `cls.f(...)`."""
    func = node.func if isinstance(node, ast.Call) else None
    if isinstance(func, ast.Name):
        return func.id
    if (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
            and func.value.id in ("self", "cls")):
        return func.attr
    return None


class _Module:
    """One module's scopes, so a dialog's text is followed back to the literal it came from."""

    def __init__(self, tree, follow: bool) -> None:
        self.follow = follow
        self.names = _bindings(tree)
        self.attrs, self.functions, self.calls, self.scope, self.locals = {}, {}, {}, {}, {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for name, values in _bindings(node).items():
                    self.attrs.setdefault(name, []).extend(values)
            elif isinstance(node, DEFS):
                self.functions.setdefault(node.name, []).append(node)
                self.locals[id(node)] = _bindings(node)
        for root in [tree] + [n for n in ast.walk(tree) if isinstance(n, DEFS + (ast.ClassDef,))]:
            local = self.locals.get(id(root))
            for node in _own(root):
                self.scope[id(node)] = (root, local)
                if _callee(node) in self.functions:
                    self.calls.setdefault(_callee(node), []).append((node, root, local))

    def words(self, expr, root, local, seen=frozenset()) -> str:
        """The longest wording one of this module's literals gives `expr`; "" when none reaches it."""
        if isinstance(expr, ast.Constant):
            return expr.value if _worded(expr.value) else ""
        parts, texts = [], []
        if isinstance(expr, ast.JoinedStr):
            texts.append("".join(p.value for p in expr.values if isinstance(p, ast.Constant)))
            parts = [p.value for p in expr.values if isinstance(p, ast.FormattedValue)]
        elif isinstance(expr, ast.BinOp):
            parts = [expr.left, expr.right]
            if not self.follow and isinstance(expr.op, ast.Mod):
                parts = [expr.left]    # outside the interface a template's arguments are not read
        elif not self.follow:
            pass
        elif isinstance(expr, ast.BoolOp):
            parts = expr.values
        elif isinstance(expr, ast.IfExp):
            parts = [expr.body, expr.orelse]
        elif isinstance(expr, (ast.Tuple, ast.List, ast.Set)):
            parts = expr.elts
        elif isinstance(expr, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            parts = [expr.elt]
        elif isinstance(expr, ast.Starred):
            parts = [expr.value]
        elif isinstance(expr, ast.Subscript):
            texts = self._item(expr, root, local, seen)
        elif isinstance(expr, ast.Call):
            texts = self._called(expr, root, local, seen)
        elif self.follow and isinstance(expr, ast.Name):
            texts = self._named(expr.id, root, local, seen)
        elif self.follow and isinstance(expr, ast.Attribute):
            texts = self._attribute(expr, seen)
        texts += [self.words(part, root, local, seen) for part in parts]
        return max((text for text in texts if _worded(text)), key=len, default="")

    def _item(self, expr, root, local, seen) -> list:
        """`x[n]`: element n of a tuple, or of what a function of this module returns."""
        at = expr.slice.value if isinstance(expr.slice, ast.Constant) else None
        value = expr.value
        if isinstance(at, int) and isinstance(value, (ast.Tuple, ast.List)) \
                and at < len(value.elts):
            return [self.words(value.elts[at], root, local, seen)]
        if isinstance(at, int) and self.follow and _callee(value) in self.functions:
            return self._returned(_callee(value), at, seen)
        return [self.words(value, root, local, seen)]

    def _called(self, call, root, local, seen) -> list:
        """A call's words: a join's items, a wrapper's argument, a callback's, or what returns."""
        func, args = call.func, call.args
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if isinstance(func, ast.Attribute) and name == "join":
            args = args[:1]    # the separator is glue, never wording
        elif isinstance(func, ast.Attribute) and name in ("format", "strip", "rstrip", "lstrip"):
            args = [func.value] + list(args)
        elif name in WRAPPERS:
            pass
        elif self.follow and _callee(call) in self.functions:
            return self._returned(_callee(call), None, seen)
        elif not (self.follow and isinstance(func, ast.Name) and self._parameter(func.id, root)):
            return []    # another module's answer; a callback handed in hands its argument on
        return [self.words(arg, root, local, seen) for arg in args]

    def _returned(self, name, at, seen) -> list:
        """What `name` returns, element `at` of a returned tuple when `at` is given."""
        if ("call", name) in seen:
            return []
        seen = seen | {("call", name)}
        texts = []
        for function in self.functions.get(name, ()):
            local = self.locals[id(function)]
            for node in _own(function):
                if not isinstance(node, ast.Return) or node.value is None:
                    continue
                value = node.value
                if at is not None and isinstance(value, (ast.Tuple, ast.List)) \
                        and at < len(value.elts):
                    value = value.elts[at]
                elif at is not None and _callee(value) in self.functions:
                    texts += self._returned(_callee(value), at, seen)
                    continue
                texts.append(self.words(value, function, local, seen))
        return texts

    @staticmethod
    def _parameter(name, root) -> bool:
        if not isinstance(root, DEFS):
            return False
        args = root.args
        return name in [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]

    def _named(self, name, root, local, seen) -> list:
        """A name's words: what its scope binds it to, its callers' arguments, or the module's."""
        key = ("name", name, id(root))
        if key in seen:
            return []
        seen = seen | {key}
        if local is not None and name in local:
            return [self.words(value, root, local, seen) for value in local[name]]
        if self._parameter(name, root):
            return self._argued(root, name, seen)
        return [self.words(value, None, None, seen) for value in self.names.get(name, ())]

    def _argued(self, function, name, seen) -> list:
        """Every argument this module's callers pass `function` for parameter `name`, and its default."""
        args = function.args
        positional = [a.arg for a in args.posonlyargs + args.args]
        defaults = dict(zip(positional[len(positional) - len(args.defaults):], args.defaults))
        defaults.update((a.arg, d) for a, d in zip(args.kwonlyargs, args.kw_defaults) if d)
        texts = [self.words(defaults[name], None, None, seen)] if name in defaults else []
        at = positional.index(name) if name in positional else -1
        if positional[:1] in (["self"], ["cls"]):
            at -= 1    # a method's callers do not pass the receiver
        for call, root, local in self.calls.get(function.name, ()):
            if 0 <= at < len(call.args):
                texts.append(self.words(call.args[at], root, local, seen))
            texts += [self.words(k.value, root, local, seen)
                      for k in call.keywords if k.arg == name]
        return texts

    def _attribute(self, expr, seen) -> list:
        """`self.X`, `cls.X` or `Class.X`: what a class body of this module binds X to."""
        owner = expr.value
        if not (isinstance(owner, ast.Name)
                and (owner.id in ("self", "cls") or owner.id[:1].isupper())):
            return []
        key = ("attr", expr.attr)
        if key in seen:
            return []
        return [self.words(value, None, None, seen | {key})
                for value in self.attrs.get(expr.attr, ())]


def _texts(call, boxes, interface) -> list:
    """The arguments of `call` a person reads: a dialog's, a sink's or a message box's."""
    func = call.func
    if not isinstance(func, ast.Attribute):
        return []
    owner, name = func.value, func.attr
    if name in HOU_DIALOGS:
        return call.args[:1] + [k.value for k in call.keywords if k.arg in TEXT_KEYWORDS]
    if name in SINKS and isinstance(owner, ast.Name) and owner.id == "debug":
        return call.args[:1] if name != "note" or interface else []
    if name in BOX_STATICS and ast.unparse(owner).endswith("QMessageBox"):
        return call.args[1:3]
    if name in BOX_SETTERS and isinstance(owner, ast.Name) and owner.id in boxes:
        return call.args[:1]
    return []


def _spelled_messages(tree, where: str = "panel") -> list:
    """[(line, words)] for each dialog in `tree` whose text carries words of its own module."""
    interface = where.replace("\\", "/").split("/")[0] in INTERFACE
    module = _Module(tree, follow=interface)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        root, local = module.scope.get(id(node), (tree, None))
        boxes = {name for name, values in (local or {}).items() if any(
            isinstance(value, ast.Call) and ast.unparse(value.func).endswith("QMessageBox")
            for value in values)}
        for arg in _texts(node, boxes, interface):
            words = module.words(arg, root, local)
            if words:
                found.append((node.lineno, words))
    return found


class NoDialogSpellsItsOwnMessage(unittest.TestCase):
    """A message written at the call site is a second home for words the design owns, and the one place a Figma edit cannot reach."""

    def test_no_message_literal_survives_at_a_call_site(self):
        offenders = []
        for path in _sources():
            where = os.path.relpath(path, _PKG)
            with open(path, encoding="utf-8") as handle:
                try:
                    tree = ast.parse(handle.read(), filename=path)
                except SyntaxError:
                    continue
            for line, words in _spelled_messages(tree, where):
                offenders.append("%s:%d  %r" % (where, line, words[:48]))
        self.assertEqual(
            [], offenders,
            "a dialog spells its own message instead of taking one from "
            "messages.py - a Figma edit can never reach it:\n  "
            + "\n  ".join(offenders))

    SEEN = (    # every shape a dialog's words have been spelled in, each reported once
        'ui.displayMessage("a sentence long enough")',
        'ui.displayMessage("a sentence long enough %s" % x)',
        'ui.displayMessage("Amaze: " + reason)',
        'ui.displayMessage(x + "a sentence long enough")',
        'ui.displayMessage(f"a sentence {x} long enough")',
        'ui.displayMessage(messages.X, help="Each one comes back whole.")',
        'ui.displayMessage(messages.X, buttons=("Save New", messages.CANCEL))',
        'ui.displayMessage(messages.X, title="Save to " + branding.APP_NAME)',
        'hou.ui.selectFromList(rows, message=messages.X, column_header="Section")',
        'QtWidgets.QMessageBox.warning(self, "Amaze", messages.X)',
        'def f():\n    box = QtWidgets.QMessageBox()\n    box.addButton("Show in Folder", r)',
        'debug.note("the log could not be cleared (%s)" % why)',
        'debug.refuse("%s has no ramp to take it" % name)',
        'X = "a sentence long enough"\nui.displayMessage(X)',
        'class P:\n    X = "a sentence"\n    def f(self):\n        ui.displayMessage(self.X)',
        'def f(x):\n    said = messages.X % x\n    said += "A sentence more."\n'
        '    ui.displayMessage(said)',
        'def f():\n    lines = []\n    lines.append(f"{x}: crashed")\n'
        '    ui.displayMessage(messages.X % "\\n".join(lines))',
        'def g():\n    return ["Close"], ["close"]\ndef f():\n    shown, _keys = g()\n'
        '    ui.displayMessage(messages.X, buttons=tuple(shown))',
        'def pick(message):\n    ui.selectFromList([], message=message)\n'
        'def f():\n    pick("Which copy do you want?")',
        'def f(say):\n    failures = ["a failed: why"]\n'
        '    ui.displayMessage(say("\\n".join(failures)))',
    )
    UNSEEN = (    # words that are the register's, data, or glue
        'ui.displayMessage(messages.X % "\\n".join(x))',
        'ui.displayMessage(messages.X % (n, "s" if n != 1 else ""), buttons=messages.B)',
        'ui.displayMessage(messages.X % (snap["when"], db.section_label("library.json")))',
        'def g():\n    return [messages.CLOSE], ["close"]\ndef f():\n    shown, _keys = g()\n'
        '    ui.displayMessage(messages.X, buttons=tuple(shown))',
    )

    def test_the_scan_can_see_a_literal(self):
        """A scanner matching nothing passes forever."""
        for shape in self.SEEN:
            with self.subTest(shape=shape):
                self.assertEqual(1, len(_spelled_messages(ast.parse(shape))))
        for shape in self.UNSEEN:
            with self.subTest(shape=shape):
                self.assertEqual([], _spelled_messages(ast.parse(shape)),
                                 "words that are not the call's own were flagged")
        self.assertEqual([], _spelled_messages(ast.parse(
            'debug.note("a sentence long enough")'), "core/x.py"),
            "a core note was read as dialog text")


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
