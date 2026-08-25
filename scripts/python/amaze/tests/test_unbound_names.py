"""The gate: no module may USE a sibling or stdlib module it never imported - read from the SOURCE, because neither `py_compile` nor a green suite can see it. ▸p/code-motion"""

import ast
import os
import sys
import unittest

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


class TheProjectsOldNameIsGoneFromTheCode(unittest.TestCase):
    """`$ASSETLIB` was the plugin root before the rename to Amaze; every install now sets `$AMAZE`, so no source may still read the old spelling. ▸p/updater-shape"""

    def test_no_module_reads_the_legacy_environment_variable(self):
        offenders = []
        for path in _source_files():
            with open(path, "r", encoding="utf-8") as handle:
                for number, line in enumerate(handle, 1):
                    if "ASSETLIB" in line:
                        offenders.append("%s:%d" % (
                            os.path.relpath(path, _AMAZE), number))
        self.assertEqual(
            [], offenders,
            "the pre-rename plugin root is read again in: %s - every "
            "package sets $AMAZE, so a fallback here is a second name "
            "for one thing" % ", ".join(offenders))

    def test_the_userdata_key_is_NOT_swept_up_with_it(self):
        """`assetlib_id` is stamped into node userdata on every saved material, so it is a contract with data on disk and keeps its spelling."""
        stamped = []
        for path in _source_files():
            with open(path, "r", encoding="utf-8") as handle:
                if "assetlib_id" in handle.read():
                    stamped.append(path)
        self.assertTrue(
            stamped,
            "assetlib_id vanished from the source - if it was renamed, "
            "every material already on disk lost its re-save recognition")


if __name__ == "__main__":
    unittest.main()
