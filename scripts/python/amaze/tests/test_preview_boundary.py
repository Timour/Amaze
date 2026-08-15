"""The preview engine is a BOX: name `amaze.preview`, never its insides. ▸p/preview-door"""
import ast
import os
import types
import unittest

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(PACKAGE, "preview")

DOOR = "amaze.preview"


def _python_files(root):
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in sorted(files):
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def _imports(path):
    """Every module name this file imports, in either spelling. ▸p/preview-door"""
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
        """Guards the guard: an empty package makes every assertion below vacuous."""
        self.assertTrue(os.path.isdir(ENGINE),
                        "the preview engine package is gone: %s" % ENGINE)
        inside = [os.path.basename(p) for p in _python_files(ENGINE)
                  if os.path.basename(p) != "__init__.py"]
        self.assertGreaterEqual(
            len(inside), 2,
            "the preview engine has almost nothing in it, so this file "
            "is asserting nothing: %s" % inside)

    def test_the_engine_states_its_api(self):
        """A door with nothing written on it is a wall with a hole."""
        from amaze import preview
        self.assertTrue(
            preview.__doc__,
            "preview/__init__.py carries no docstring, so the engine "
            "has no stated API")
        self.assertTrue(
            getattr(preview, "__all__", None),
            "preview/__init__.py declares no __all__, so what is inside "
            "the box and what is offered are the same thing")

    def test_a_reload_rebinds_every_name_the_door_offers(self):
        """A name the reload forgets keeps its OLD function bound. ▸p/preview-door"""
        from amaze import preview
        preview.reload_engine()
        inside = [m for m in vars(preview).values()
                  if isinstance(m, types.ModuleType)
                  and getattr(m, "__name__", "").startswith(DOOR + ".")]
        self.assertTrue(
            inside,
            "the door binds no submodule of its own, so there is nothing "
            "to compare a rebind against and this test proves nothing")
        unowned, stale = [], []
        for name in preview.__all__:
            if name == "reload_engine":
                continue
            owners = [m for m in inside if hasattr(m, name)]
            if not owners:
                unowned.append(name)
            elif all(getattr(m, name) is not getattr(preview, name)
                     for m in owners):
                stale.append(name)
        self.assertEqual(
            [], unowned,
            "the door offers these but no submodule of it defines them, "
            "so __all__ has drifted from what is behind it: %s" % unowned)
        self.assertEqual(
            [], stale,
            "reload_engine() left these bound to the code it replaced, "
            "so a dev reload refreshes everything but them: %s" % stale)

    def test_nothing_outside_reaches_past_the_door(self):
        """Naming `amaze.preview` is fine; naming anything under it is not."""
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
