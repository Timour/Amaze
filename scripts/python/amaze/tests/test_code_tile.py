"""The code tile: its Run button and pencil, and its text at half strength. ▸r/tile-from-frame"""

import os
import sys
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

from amaze import amazetheme  # noqa: E402
from amaze.actions import code as code_actions  # noqa: E402
from amaze.core import code_library  # noqa: E402
from amaze.helpers import hostos, vex_syntax  # noqa: E402
from amaze.panel import delegates  # noqa: E402
from amaze.tests import test_support  # noqa: E402


class ASnippetRunsInThisHoudini(unittest.TestCase):
    """`run_python` runs as one undo step and returns an error's last line."""

    def tearDown(self):
        for node in hou.node("/obj").children():
            if node.name().startswith("snippet_probe"):
                node.destroy()

    def test_a_snippet_runs_and_run_python_returns_an_empty_string(self):
        problem = code_actions.run_python(
            "probe", "hou.node('/obj').createNode('null', 'snippet_probe')")
        self.assertEqual("", problem)
        self.assertIsNotNone(hou.node("/obj/snippet_probe"))

    def test_a_snippet_is_one_undo_step_named_after_it(self):
        if not hou.undos.areEnabled():
            self.skipTest("undo is off in this session")
        code_actions.run_python("probe", "o = hou.node('/obj')\n"
                                "o.createNode('null', 'snippet_probe1')\n"
                                "o.createNode('null', 'snippet_probe2')")
        self.assertEqual("Run probe", hou.undos.undoLabels()[0])
        hou.undos.performUndo()
        self.assertIsNone(hou.node("/obj/snippet_probe1"))
        self.assertIsNone(hou.node("/obj/snippet_probe2"))

    def test_an_error_returns_its_last_line(self):
        for code, answer in (("1 / 0", "ZeroDivisionError: division by zero"),
                             ("x = (\n", "line ")):
            with self.subTest(code=code):
                problem = code_actions.run_python("probe", code)
                self.assertTrue(problem.startswith(answer), problem)
                self.assertNotIn("\n", problem, "more than the last line came back")


class ApplyToNodeSetsTheSnippetOrReturnsWhyNot(unittest.TestCase):
    """`apply_to_node` sets the snippet, or returns why not. ▸r/hou-errors"""

    def setUp(self):
        geo = hou.node("/obj").createNode("geo", "apply_probe")
        self.addCleanup(geo.destroy)
        self.wrangle = geo.createNode("attribwrangle")
        self.model = types.SimpleNamespace(assets=[types.SimpleNamespace(code="@Cd = 0.5;")])

    def test_the_snippet_is_set_on_the_code_parm(self):
        self.assertEqual((True, ""), code_actions.apply_to_node(self.model, 0, self.wrangle))
        self.assertEqual("@Cd = 0.5;", self.wrangle.parm("snippet").eval())

    def test_a_parm_houdini_will_not_write_returns_false_and_a_reason(self):
        """`Parm.set` raises PermissionError on a parm it will not write (hou/Parm.txt)."""
        real = hou.Parm.set

        def raises_permission_error(parm, *args, **kwargs):
            if parm.name() == "snippet":
                raise hou.PermissionError("the asset is locked")
            return real(parm, *args, **kwargs)

        with mock.patch.object(hou.Parm, "set", raises_permission_error):
            try:
                ok, reason = code_actions.apply_to_node(self.model, 0, self.wrangle)
            except hou.Error as exc:
                self.fail("a refused parm write raised %s: %s" % (type(exc).__name__, exc))
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("Could not set the parameter"), reason)
        self.assertEqual("", self.wrangle.parm("snippet").eval().strip())


SHELF_KEYS = {    # hom.zip ▸ tool_script.txt; `bbox` is "may not be present" ▸r/shelf-kwargs
    "pane", "viewport", "panename", "toolname",
    "shiftclick", "ctrlclick", "altclick", "cmdclick",
    "requestnew", "branch", "autoplace",
    "inputs", "inputnodename", "outputindex",
    "outputs", "outputnodename", "inputindex",
}


class AShelfScriptGetsItsKwargs(unittest.TestCase):
    """Run gives a snippet the `kwargs` a shelf click would, modifiers mapped per OS."""

    def test_a_shelf_script_reads_kwargs(self):
        probe = types.ModuleType("_amaze_kwargs_probe")
        sys.modules[probe.__name__] = probe
        self.addCleanup(sys.modules.pop, probe.__name__, None)
        problem = code_actions.run_python(
            "probe", "import sys\nsys.modules['_amaze_kwargs_probe'].seen = dict(kwargs)\n")
        self.assertEqual("", problem)
        seen = probe.seen
        self.assertEqual(SHELF_KEYS, set(seen))
        self.assertIsNone(seen["pane"], "a shelf click has no pane")
        self.assertIsNone(seen["viewport"])
        self.assertEqual("probe", seen["toolname"])
        self.assertEqual(([], [], "", "", -1, -1),
                         (seen["inputs"], seen["outputs"], seen["inputnodename"],
                          seen["outputnodename"], seen["outputindex"], seen["inputindex"]))
        self.assertEqual((True, False, False),
                         (seen["requestnew"], seen["branch"], seen["autoplace"]))

    def _flags(self, held, platform, swapped=True):
        with mock.patch.object(QtGui.QGuiApplication, "keyboardModifiers", return_value=held), \
                mock.patch.object(hostos, "is_macos", return_value=platform == "darwin"), \
                mock.patch.object(QtCore.QCoreApplication, "testAttribute",
                                  return_value=not swapped):
            kwargs = code_actions.shelf_kwargs("probe")
        return {k for k in ("shiftclick", "ctrlclick", "altclick", "cmdclick") if kwargs[k]}

    def test_each_modifier_reaches_its_shelf_flag(self):
        keys = QtCore.Qt.KeyboardModifier
        for held, platform, swapped, flags in (
                (keys.ControlModifier, "win32", True, {"ctrlclick"}),
                (keys.MetaModifier, "win32", True, set()),    # the Windows key
                (keys.ControlModifier, "darwin", True, {"cmdclick"}),
                (keys.MetaModifier, "darwin", True, {"ctrlclick"}),
                (keys.ControlModifier, "darwin", False, {"ctrlclick"}),
                (keys.MetaModifier, "darwin", False, {"cmdclick"}),
                (keys.ShiftModifier | keys.AltModifier, "darwin", True,
                 {"shiftclick", "altclick"})):
            with self.subTest(held=held, platform=platform, swapped=swapped):
                self.assertEqual(flags, self._flags(held, platform, swapped))


class OnlyAPythonSnippetCanRun(unittest.TestCase):
    """The Run button reads the snippet's language."""

    def _badge(self, name):
        return next(b for b in delegates.BADGES if b.name == name)

    def test_run_is_for_python_alone(self):
        for name, language, shown in (("execute", "Python", True),
                                      ("execute", "VEX", False)):
            with self.subTest(badge=name, language=language):
                self.assertEqual(shown, self._badge(name).is_on(language))


class TheCodeTextIsHalfStrength(unittest.TestCase):
    """T05B draws a code tile's text at half strength, under its Run button."""

    def test_the_brightest_text_pixel_is_half_its_colour(self):
        image = code_library.paint_code_preview("MMMMMMMM")
        brightest = max(QtGui.QColor(image.pixel(x, y)).red()
                        for x in range(image.width()) for y in range(120))
        ground = QtGui.QColor(amazetheme.TILE_GROUND).red()
        half = round(vex_syntax.DEFAULT.red() * amazetheme.CODE_TEXT_OPACITY
                     + ground * (1 - amazetheme.CODE_TEXT_OPACITY))
        self.assertLessEqual(abs(brightest - half), 2,
                             "the code text paints at %d, not half its colour's %d"
                             % (brightest, vex_syntax.DEFAULT.red()))


class TheRunButtonPixmapFollowsHoverAndPress(unittest.TestCase):
    """Rest, hover and pressed each request their own pixmap."""

    def _requested_pixmaps(self, hovered=False, pressed=False):
        role = QtCore.Qt.ItemDataRole.UserRole + 77
        requested = []

        class _RoleModel(QtCore.QAbstractListModel):
            def rowCount(self, parent=QtCore.QModelIndex()):
                return 1

            def data(self, index, r=QtCore.Qt.ItemDataRole.DisplayRole):
                return "Python" if r == role else None

        cls = delegates.AssetItemDelegate
        original = cls.__dict__["_badge_pixmap"]
        cls._badge_pixmap = staticmethod(
            lambda name, side, dpr=1.0, opacity=None: requested.append(name) or QtGui.QPixmap())
        self.addCleanup(setattr, cls, "_badge_pixmap", original)
        delegate = test_support.tile_delegate({"execute": role})
        model = _RoleModel()
        index = model.index(0, 0)
        if hovered or pressed:
            delegate.set_button_hover("execute", index, down=pressed)
        surface = QtGui.QPixmap(140, 140)
        painter = QtGui.QPainter(surface)
        try:
            delegate._paint_badges(painter, index, 0, 0, 130, 1.0)
        finally:
            painter.end()
        return requested

    def test_each_state_has_its_art(self):
        self.assertEqual(["badge_execute"], self._requested_pixmaps())
        self.assertEqual(["badge_execute_hover"], self._requested_pixmaps(hovered=True))
        self.assertEqual(["badge_execute_press"], self._requested_pixmaps(pressed=True))


class ThePanelWiresTheCodeButtons(unittest.TestCase):
    """On a real panel: Run runs the snippet and names a failure; the pencil opens its editor."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _proxy_index(self, code, language="Python"):
        model = self.panel.code_model
        name = "probe_%d" % model.rowCount()
        model.add_asset(code, name, language, "", "", False)
        row = next(r for r in range(model.rowCount()) if model.assets[r].name == name)
        index = self.panel.code_sorted_model.mapFromSource(model.index(row, 0))
        if not index.isValid():
            self.skipTest("the code grid filters the probe out")
        return index, row

    def test_the_run_button_is_the_code_tiles_alone(self):
        self.assertIn("execute", self.panel.code_delegate._badge_clicks)
        self.assertNotIn("execute", self.panel.asset_delegate._badge_clicks,
                         "the Node tiles got the Run button")
        self.assertNotIn("edit", delegates.BADGE, "a code tile has no Edit badge; Edit is in its menu")

    def _click(self, badge, index):
        with mock.patch.object(self.panel, "current_section", "code"):
            self.panel.code_delegate._badge_clicks[badge](index)

    def test_a_failing_run_calls_debug_refuse_with_the_snippets_name(self):
        index, row = self._proxy_index("1 / 0")
        name = self.panel.code_model.assets[row].name
        with mock.patch("amaze.core.debug.refuse") as refuse:
            self._click("execute", index)
        refuse.assert_called_once()
        self.assertIn(name, refuse.call_args[0][0])
        self.assertIn("ZeroDivisionError", refuse.call_args[0][0])

    def test_generic_shows_the_generic_image_and_preview_the_painted_code(self):
        from amaze.core import tile_icons
        _index, row = self._proxy_index("print(1)")
        model = self.panel.code_model
        self.addCleanup(model.set_tile_icon, row, {})
        generic = tile_icons.generic_image(code_library.CodeLibrary.TILE_FACE)

        def shown():
            return model.data(model.index(row, 0), QtCore.Qt.ItemDataRole.DecorationRole)

        self.assertNotEqual(generic, shown(), "a code tile's default is not its painted code")
        model.set_tile_icon(row, {"face": "generic"})
        self.assertEqual(generic, shown())


if __name__ == "__main__":
    unittest.main()
