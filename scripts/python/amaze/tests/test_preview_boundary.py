"""The preview engine is a BOX, and this is what makes that true.

`amaze/preview/` is the scene a material thumbnail is rendered in - the
most egMatLib-derived part of Amaze still doing a job of its own
(overview.md 4h). Boxing it is only worth something if callers actually
go through its door: a package everyone reaches into is a directory,
not an engine, and "swap the preview engine" stops being a sentence
anyone can act on.

So: the rest of the tree may name `amaze.preview`. It may not import
what is inside it.

WHY A TEST AND NOT A CONVENTION. Before the move, `render/thumbs.py`
imported `thumbnail_scene` directly and `panel/panel.py` imported both
submodules to reload them - which is exactly the shape this forbids, so
this file was RED on the tree that existed before the package did. A
boundary nothing checks is a boundary that lasts until the next hurry.
"""
import ast
import os
import unittest

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(PACKAGE, "preview")

#: How the engine is named from outside. Everything else in the package
#: is its own business.
DOOR = "amaze.preview"


def _python_files(root):
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in sorted(files):
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def _imports(path):
    """Every module name this file imports, however it spells it.

    Both forms matter and they fail differently: `from amaze.preview
    import thumbnail_scene` binds the submodule, and `import
    amaze.preview.thumbnail_scene` binds the top package but still
    names the internal path. Reading the AST rather than grepping,
    because a comment mentioning the module is not an import - the
    mistake practice.md records against a guard that matched prose.
    """
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                continue
            found.add(node.module)
            for alias in node.names:
                found.add("%s.%s" % (node.module, alias.name))
    return found


class ThePreviewEngineIsAPackageWithADoor(unittest.TestCase):

    def test_the_engine_has_modules_to_protect(self):
        """Guards the guard: an empty package makes every assertion
        below vacuously true, which is how a boundary test survives the
        deletion of the thing it protects."""
        self.assertTrue(os.path.isdir(ENGINE),
                        "the preview engine package is gone: %s" % ENGINE)
        inside = [os.path.basename(p) for p in _python_files(ENGINE)
                  if os.path.basename(p) != "__init__.py"]
        self.assertGreaterEqual(
            len(inside), 2,
            "the preview engine has almost nothing in it, so this file "
            "is asserting nothing: %s" % inside)

    def test_the_engine_states_its_api(self):
        """__init__.py is the door, and a door with nothing written on
        it is a wall with a hole. It is also the one file the system
        map guard skips, so nothing else would notice it going empty."""
        init = os.path.join(ENGINE, "__init__.py")
        with open(init, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=init)
        exported = set()
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "__all__" not in names:
                continue
            if isinstance(node.value, (ast.List, ast.Tuple)):
                exported = {element.value for element in node.value.elts
                            if isinstance(element, ast.Constant)}
        self.assertTrue(
            ast.get_docstring(tree),
            "preview/__init__.py carries no docstring, so the engine "
            "has no stated API")
        self.assertTrue(
            exported,
            "preview/__init__.py declares no __all__, so what is inside "
            "the box and what is offered are the same thing")

    def test_nothing_outside_reaches_past_the_door(self):
        """The whole point. Naming `amaze.preview` is fine; naming
        anything under it is not."""
        offenders = []
        for path in _python_files(PACKAGE):
            if path.startswith(ENGINE + os.sep):
                continue
            for name in _imports(path):
                if name.startswith(DOOR + ".") and name != DOOR:
                    offenders.append("%s imports %s" % (
                        os.path.relpath(path, PACKAGE), name))
        self.assertEqual(
            [], sorted(offenders),
            "these reach past the preview engine's API into its "
            "internals, so it is a directory rather than an engine and "
            "nothing could be swapped for it: %s" % "; ".join(
                sorted(offenders)))


if __name__ == "__main__":
    unittest.main()
