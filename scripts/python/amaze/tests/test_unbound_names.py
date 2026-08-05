"""The gate: no module may USE a sibling module it never imported.

2026-08-02. Three model modules did `from amaze.helpers import helpers`
and then called `ui_helpers.tooltip_text(...)` - a rename that moved the
CALL SITES and left the import lines behind. Every one of them compiles
perfectly and raises `NameError` only when the line actually runs, which
here is inside `QAbstractListModel.data()`: so every hover tooltip on an
Online, Code or Colour tile threw, five times in one session, and the
feature read as "occasionally stretches across the screen" rather than
as broken.

practice.md already records the family - *moving code between modules
loses its imports, and only RUNNING finds out* - and the reason it keeps
costing sessions is that neither `py_compile` nor a green suite can see
it. A behaviour test only catches the line it happens to execute, and
these lines are in tooltip handlers nothing clicks.

So this reads the SOURCE, per practice.md's rule that a source-derived
test must parse STRUCTURE rather than match prose: it resolves the names
this package actually contains, then asserts that any module referring to
one of them by name has bound it. It is deliberately narrow - only the
project's OWN module names - because that is the whole class, and a
general undefined-name linter would drown it in false positives.
"""

import ast
import os
import unittest

_AMAZE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _package_module_names() -> set:
    """Every module name inside the amaze package - `ui_helpers`,
    `hostos`, `debug`, and so on. Resolved from the tree rather than
    listed, so a new module joins this gate by existing."""
    names = set()
    for root, dirs, files in os.walk(_AMAZE):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for filename in files:
            if filename.endswith(".py") and filename != "__init__.py":
                names.add(filename[:-3])
    return names


def _source_files() -> list:
    """The shipped modules. Tests are excluded: a test binds names
    through the harness and is not what ships to a user's Houdini."""
    found = []
    for root, dirs, files in os.walk(_AMAZE):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "tests")]
        for filename in files:
            if filename.endswith(".py"):
                found.append(os.path.join(root, filename))
    return sorted(found)


def _bound_names(tree: ast.AST) -> set:
    """Every name this module gives a meaning to, by ANY route.

    Imports are the interesting one, but a name can equally be a local,
    a parameter, a def or a class - and counting only imports would
    report a module that legitimately has a local called `library`. A
    function-local import counts: `ast.walk` reaches it, which is
    correct, because that is exactly how these three modules import.
    """
    bound = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound.add(alias.asname or alias.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bound.add(node.name)
            args = node.args
            for arg in (list(args.args) + list(args.posonlyargs)
                        + list(args.kwonlyargs)):
                bound.add(arg.arg)
            for maybe in (args.vararg, args.kwarg):
                if maybe is not None:
                    bound.add(maybe.arg)
        elif isinstance(node, ast.ClassDef):
            bound.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, ast.alias):
            continue
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.Global):
            bound.update(node.names)
    return bound


def _used_module_names(tree: ast.AST, package: set) -> dict:
    """Sibling-module names this file READS, with a line number each."""
    used = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Load)
                and node.id in package):
            used.setdefault(node.id, node.lineno)
    return used


class NoModuleUsesAnUnboundSibling(unittest.TestCase):

    def test_every_referenced_module_is_imported(self):
        package = _package_module_names()
        # The gate is only meaningful if the tree resolved - an empty
        # set would pass every file without testing anything, which is
        # the vacuous-pin shape practice.md warns about.
        self.assertIn("ui_helpers", package)
        self.assertIn("hostos", package)

        offences = []
        for path in _source_files():
            with open(path, encoding="utf-8") as handle:
                source = handle.read()
            tree = ast.parse(source, filename=path)
            bound = _bound_names(tree)
            for name, lineno in _used_module_names(tree, package).items():
                if name not in bound:
                    offences.append(
                        "%s:%d uses %s and never imports it"
                        % (os.path.relpath(path, _AMAZE), lineno, name))

        self.assertEqual(
            [], offences,
            "a module calls into a sibling it never imported - this "
            "compiles, and raises NameError only when the line runs:\n  "
            + "\n  ".join(offences))


if __name__ == "__main__":
    unittest.main()
