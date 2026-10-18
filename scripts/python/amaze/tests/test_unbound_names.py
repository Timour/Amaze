"""The gate: no module may USE a sibling or stdlib module it never imported - read from the SOURCE, because neither `py_compile` nor a green suite can see it. ▸p/code-motion"""

import ast
import os
import sys
import unittest

from amaze.tests import test_support  # noqa: F401

_AMAZE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _watched_module_names() -> set:
    """Every module name this gate will hold a file to: the amaze package's own, plus the standard library's. ▸p/code-motion"""
    names = set(sys.stdlib_module_names)
    for root, dirs, files in os.walk(_AMAZE):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for filename in files:
            if filename.endswith(".py") and filename != "__init__.py":
                names.add(filename[:-3])
    return names


def _source_files() -> list:
    """The shipped modules - tests excluded, since a test binds names through the harness and is not what ships. ▸p/code-motion"""
    found = []
    for root, dirs, files in os.walk(_AMAZE):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "tests")]
        for filename in files:
            if filename.endswith(".py"):
                found.append(os.path.join(root, filename))
    return sorted(found)


def _bound_names(tree: ast.AST) -> set:
    """Every name this module gives a meaning to by ANY route - import, local, parameter, def or class, function-local imports included. ▸p/code-motion"""
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
        package = _watched_module_names()
        # an empty set would pass every file without testing anything - the vacuous-pin shape ▸p/code-motion
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


_FUNCTION_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _own_nodes(scope):
    """The nodes evaluated in `scope` itself; a nested function's body is its own scope, left out."""
    pending = list(scope.body) if isinstance(scope.body, list) else [scope.body]
    while pending:
        node = pending.pop()
        yield node
        if isinstance(node, _FUNCTION_SCOPES):
            pending.extend(getattr(node, "decorator_list", []))
            pending.extend(d for d in node.args.defaults + node.args.kw_defaults if d is not None)
        else:
            pending.extend(ast.iter_child_nodes(node))


def _names_bound_by(node) -> set:
    """What one statement-level node binds: an import, a store, a def or class, an except name."""
    if isinstance(node, ast.Import):
        return {(alias.asname or alias.name).split(".")[0] for alias in node.names}
    if isinstance(node, ast.ImportFrom):
        return {alias.asname or alias.name for alias in node.names}
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
        return {node.id}
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, ast.ExceptHandler) and node.name:
        return {node.name}
    return set()


def _scope_bindings(scope) -> set:
    """Every name a function binds for itself: parameters, imports, stores and nested defs."""
    args = scope.args
    bound = {arg.arg for arg in args.posonlyargs + args.args + args.kwonlyargs}
    bound.update(maybe.arg for maybe in (args.vararg, args.kwarg) if maybe is not None)
    for node in _own_nodes(scope):
        bound |= _names_bound_by(node)
    return bound


def _module_bindings(tree) -> set:
    """The names a module binds at its top level, which every function in it can read."""
    bound, pending = set(), list(tree.body)
    while pending:
        node = pending.pop()
        bound |= _names_bound_by(node)
        if not isinstance(node, _FUNCTION_SCOPES + (ast.ClassDef,)):
            pending.extend(ast.iter_child_nodes(node))
    return bound


def _function_scoped_misses(tree, package) -> list:
    """(line, name) where a function reads a sibling neither it, an enclosing one nor the module binds."""
    module_bound = _module_bindings(tree)
    misses = set()

    def visit(node, enclosing):
        for child in ast.iter_child_nodes(node):
            if not isinstance(child, _FUNCTION_SCOPES):
                visit(child, enclosing)
                continue
            bound = enclosing | _scope_bindings(child)
            for inner in _own_nodes(child):
                if (isinstance(inner, ast.Name) and isinstance(inner.ctx, ast.Load)
                        and inner.id in package and inner.id not in module_bound
                        and inner.id not in bound):
                    misses.add((inner.lineno, inner.id))
            visit(child, bound)

    visit(tree, frozenset())
    return sorted(misses)


class AFunctionImportsWhatItReads(unittest.TestCase):
    """A sibling imported only inside functions is imported by every function that reads it."""

    def test_the_check_names_a_function_that_forgot_the_import(self):
        source = ("def a():\n    from amaze.helpers import helpers\n    return helpers.x\n\n"
                  "def b():\n    return helpers.y\n\n"
                  "def c():\n    from amaze.helpers import helpers\n"
                  "    return lambda: helpers.z\n")
        self.assertEqual([(6, "helpers")],
                         _function_scoped_misses(ast.parse(source), {"helpers"}))

    def test_no_function_reads_a_sibling_only_another_function_imported(self):
        package = _watched_module_names()
        offences = []
        for path in _source_files():
            with open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=path)
            offences.extend("%s:%d reads %s and does not import it"
                            % (os.path.relpath(path, _AMAZE), line, name)
                            for line, name in _function_scoped_misses(tree, package))
        self.assertEqual(
            [], offences,
            "a function reads a sibling that only another function imports, which "
            "raises NameError only when it runs:\n  " + "\n  ".join(offences))


class TheProjectsOldNameIsGoneFromTheCode(unittest.TestCase):
    """`$ASSETLIB` was the plugin root before the rename to Amaze; every install now sets `$AMAZE`, so no source may still read the old spelling. ▸p/updater-shape"""

    def test_no_shipped_file_names_the_old_apps(self):
        """Pre-1.0 names are gone: compatibility starts at Amaze 1.0. ▸p/compat-starts-at-1-0"""
        import re
        old = re.compile(r"\bMatLib\w*|\bAssetLib\b|ASSETLIB")    # egMatLib, the credited original, is not matched
        offenders = []
        shipped = _source_files() + [os.path.join(
            _AMAZE, "..", "..", "..", "python_panels", "Amaze.pypanel")]
        for path in shipped:
            with open(path, "r", encoding="utf-8") as handle:
                for number, line in enumerate(handle, 1):
                    if old.search(line):
                        offenders.append("%s:%d" % (
                            os.path.relpath(path, _AMAZE), number))
        self.assertEqual([], offenders,
                         "an old app name is back in: %s" % offenders)


if __name__ == "__main__":
    unittest.main()
