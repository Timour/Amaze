"""Snippet run: one test per requirement in docs/requirements/snippet-run.md."""

import os
import sys
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from amaze import messages  # noqa: E402
from amaze.helpers import hostos  # noqa: E402
from amaze.tests import test_support  # noqa: E402

try:    # without Houdini every test here skips
    import hou
    from amaze.actions import code as code_actions
    from amaze.core import debug
    from amaze.pane import drop_placement
    from amaze.sections import code as code_section
except ImportError:
    hou = None

KEYS = QtCore.Qt.KeyboardModifier
SHELF_KEYS = {"pane", "viewport", "panename", "toolname", "shiftclick", "ctrlclick", "altclick",
              "cmdclick", "requestnew", "branch", "autoplace", "inputs", "inputnodename",
              "outputindex", "outputs", "outputnodename", "inputindex"}    # ▸r/shelf-kwargs


@unittest.skipUnless(hou, "Houdini is not loaded")
class _Snippets(unittest.TestCase):
    """A SOP network with two wrangles, and the Code section over one snippet."""

    def setUp(self):
        self.geo = hou.node("/obj").createNode("geo", "cd_geo")
        self.addCleanup(test_support.drop_node, self.geo)
        self.wrangle, self.other = (self.geo.createNode("attribwrangle") for _ in range(2))
        self.addCleanup(hou.undos.clear)
        self.refused = []
        patcher = mock.patch.object(debug, "refuse", lambda reason, **k: self.refused.append(reason))
        patcher.start()
        self.addCleanup(patcher.stop)

    def section(self, code: str, language: str = "VEX"):
        """The Code section over one snippet, and the index a drop or a double-click gives it."""
        snippet = types.SimpleNamespace(code=code, name="cd snippet", renderer=language)
        pane = types.SimpleNamespace(
            code_model=types.SimpleNamespace(assets=[snippet]), prefs=types.SimpleNamespace(),
            code_sorted_model=types.SimpleNamespace(mapToSource=lambda index: index))
        pane.drop_placement = drop_placement.DropPlacement(pane)
        index = types.SimpleNamespace(isValid=lambda: True, row=lambda: 0)
        return code_section.CodeSection(pane), index

    @staticmethod
    def values(node) -> dict:
        return {parm.name(): parm.eval() for parm in node.parms()}


class RunTest(_Snippets):

    def test_cd01_a_failing_snippet_shows_its_last_line_and_its_changes_are_one_undo_step(self):
        for ending, said in (("1 / 0", "ZeroDivisionError: division by zero"),
                             ("raise SystemExit(3)", "SystemExit: 3")):
            with self.subTest(ending):
                hou.undos.clear()
                code = "for name in ('cd01_a', 'cd01_b'):\n    hou.node('/obj').createNode('null', name)\n"
                problem = code_actions.run("cd01", code + ending, "Python")
                self.assertEqual(messages.SNIPPET_RUN_FAILED % ("cd01", said), problem)
                self.assertEqual(("Run cd01",), hou.undos.undoLabels())
                hou.undos.performUndo()
                self.assertEqual((None, None), (hou.node("/obj/cd01_a"), hou.node("/obj/cd01_b")))

    def test_cd20_run_gives_the_snippet_a_shelf_clicks_kwargs_as_one_named_undo_step(self):
        probe = types.ModuleType("_amaze_cd20")
        self.addCleanup(sys.modules.pop, probe.__name__, None)
        sys.modules[probe.__name__] = probe
        hou.undos.clear()
        code = "import sys\nsys.modules['_amaze_cd20'].seen = dict(kwargs)\nhou.node('/obj/cd_geo').setComment('ran')"
        self.assertEqual("", code_actions.run("cd20", code, "Python", KEYS.ShiftModifier))
        self.assertEqual(SHELF_KEYS, set(probe.seen))
        self.assertEqual(("cd20", True), (probe.seen["toolname"], probe.seen["shiftclick"]))
        self.assertEqual(("Run cd20",), hou.undos.undoLabels())
        for held, mac, swapped, flags in ((KEYS.ControlModifier, False, True, {"ctrlclick"}),
                                          (KEYS.ControlModifier, True, True, {"cmdclick"}),
                                          (KEYS.MetaModifier, True, True, {"ctrlclick"}),
                                          (KEYS.MetaModifier, True, False, {"cmdclick"})):
            with mock.patch.object(hostos, "is_macos", return_value=mac), \
                    mock.patch.object(QtCore.QCoreApplication, "testAttribute", return_value=not swapped):
                given = code_actions.shelf_kwargs("cd20", held)
            self.assertEqual(flags, {key for key in ("ctrlclick", "cmdclick") if given[key]})

    def test_cd21_only_a_python_snippet_runs(self):
        for language in ("VEX", "OpenCL", "Code", ""):
            with self.subTest(language):
                problem = code_actions.run("cd21", "hou.node('/obj/cd_geo').setComment('ran')", language)
                self.assertEqual(messages.SNIPPET_NOT_PYTHON % ("cd21", language or "Code"), problem)
                self.assertEqual("", self.geo.comment(), "a snippet in another language ran")


class SetTest(_Snippets):

    def test_cd02_setting_a_snippet_changes_only_the_code_parameter_as_one_undo_step(self):
        section, index = self.section("@Cd = 0.5;")
        before, other = self.values(self.wrangle), self.values(self.other)
        hou.undos.clear()
        self.assertTrue(section.drop_code_at_release(index, self.wrangle))
        after = self.values(self.wrangle)
        self.assertEqual({"snippet": "@Cd = 0.5;"},
                         {name: value for name, value in after.items() if before[name] != value})
        self.assertEqual((other, ("Amaze Apply Code Snippet",)), (self.values(self.other), hou.undos.undoLabels()))
        real = hou.Parm.set

        def refused(parm, *args, **kwargs):
            if parm.name() == "snippet":
                raise hou.PermissionError("the parameter is locked")
            return real(parm, *args, **kwargs)
        with mock.patch.object(hou.Parm, "set", refused):
            self.assertFalse(section.drop_code_at_release(self.section("@P = 0;")[1], self.wrangle))
        self.assertEqual("@Cd = 0.5;", self.wrangle.parm("snippet").eval())
        self.assertIn("the parameter is locked", self.refused[-1])

    def test_cd22_a_snippet_replaces_a_nodes_code_or_makes_a_node_for_its_language(self):
        saved = "  // kept as saved\n@Cd = {1, 0, 0};\n\n"
        self.wrangle.parm("snippet").set("@P = 0;")
        section, index = self.section(saved)
        with mock.patch.object(hou, "ui", create=True) as asked:
            self.assertTrue(section.drop_code_at_release(index, self.wrangle))
        self.assertEqual((saved, []), (self.wrangle.parm("snippet").eval(), asked.mock_calls))
        before = set(self.geo.children())
        self.assertTrue(section.create_code_node_in(index, self.geo))
        made, = set(self.geo.children()) - before
        self.assertEqual(("attribwrangle", saved), (made.type().name(), made.parm("snippet").eval()))
        objects = set(hou.node("/obj").children())
        self.assertFalse(section.create_code_node_in(index, hou.node("/obj")))
        self.assertEqual(objects, set(hou.node("/obj").children()))


if __name__ == "__main__":
    unittest.main()
