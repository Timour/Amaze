"""The code tile: its Run button and pencil, and its text at half strength. ▸r/tile-from-frame"""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402

from amaze import amazetheme  # noqa: E402
from amaze.core import code_library  # noqa: E402
from amaze.helpers import vex_syntax  # noqa: E402
from amaze.panel import delegates  # noqa: E402
from amaze.tests import test_support  # noqa: E402


class ASnippetRunsInThisHoudini(unittest.TestCase):
    """`run_python` runs as one undo step and answers an error by its last line."""

    def tearDown(self):
        for node in hou.node("/obj").children():
            if node.name().startswith("snippet_probe"):
                node.destroy()

    def test_a_snippet_runs_and_answers_nothing(self):
        problem = code_library.run_python(
            "probe", "hou.node('/obj').createNode('null', 'snippet_probe')")
        self.assertEqual("", problem)
        self.assertIsNotNone(hou.node("/obj/snippet_probe"))

    def test_a_snippet_is_one_undo_step_named_after_it(self):
        if not hou.undos.areEnabled():
            self.skipTest("undo is off in this session")
        code_library.run_python("probe", "o = hou.node('/obj')\n"
                                "o.createNode('null', 'snippet_probe1')\n"
                                "o.createNode('null', 'snippet_probe2')")
        self.assertEqual("Run probe", hou.undos.undoLabels()[0])
        hou.undos.performUndo()
        self.assertIsNone(hou.node("/obj/snippet_probe1"))
        self.assertIsNone(hou.node("/obj/snippet_probe2"))

    def test_an_error_answers_its_last_line(self):
        self.assertEqual("ZeroDivisionError: division by zero",
                         code_library.run_python("probe", "1 / 0"))

    def test_a_syntax_error_names_its_line(self):
        self.assertTrue(code_library.run_python("probe", "x = (\n").startswith("line "))


class OnlyAPythonSnippetCanRun(unittest.TestCase):
    """The Run button reads the snippet's language; every snippet has the pencil."""

    def _badge(self, name):
        return next(b for b in delegates.BADGES if b.name == name)

    def test_python_runs_and_vex_does_not(self):
        self.assertTrue(self._badge("execute").shows("Python"))
        self.assertFalse(self._badge("execute").shows("VEX"))

    def test_every_snippet_has_the_pencil(self):
        for language in ("Python", "VEX", "OpenCL", "Code"):
            self.assertTrue(self._badge("edit").shows(language))


class TheCodeTextIsHalfStrength(unittest.TestCase):
    """T05B draws a code tile's text at half strength, under its Run button."""

    def test_the_brightest_text_pixel_is_half_its_colour(self):
        image = code_library.paint_code_preview("MMMMMMMM")
        brightest = max(QtGui.QColor(image.pixel(x, y)).red()
                        for x in range(image.width()) for y in range(120))
        half = round(vex_syntax.DEFAULT.red() * amazetheme.CODE_TEXT_OPACITY)
        self.assertLessEqual(abs(brightest - half), 2,
                             "the code text paints at %d, not half its colour's %d"
                             % (brightest, vex_syntax.DEFAULT.red()))


class TheRunButtonAnswersThePointer(unittest.TestCase):
    """Rest, hover and held down each ask for their own art."""

    def _asked(self, hovered=False, pressed=False):
        role = QtCore.Qt.ItemDataRole.UserRole + 77
        asked = []

        class _RoleModel(QtCore.QAbstractListModel):
            def rowCount(self, parent=QtCore.QModelIndex()):
                return 1

            def data(self, index, r=QtCore.Qt.ItemDataRole.DisplayRole):
                return "Python" if r == role else None

        cls = delegates.AssetItemDelegate
        original = cls.__dict__["_badge_pixmap"]
        cls._badge_pixmap = staticmethod(
            lambda name, side, dpr=1.0: asked.append(name) or QtGui.QPixmap())
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
        return asked

    def test_each_state_has_its_art(self):
        self.assertEqual(["badge_execute"], self._asked())
        self.assertEqual(["badge_execute_hover"], self._asked(hovered=True))
        self.assertEqual(["badge_execute_press"], self._asked(pressed=True))


class ThePanelWiresTheCodeButtons(unittest.TestCase):
    """On a real panel: Run runs the snippet and names a failure; the pencil opens its editor."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    @classmethod
    def tearDownClass(cls):
        try:
            test_support.stop_panel_workers(cls.panel)
        except Exception:                                 # noqa: BLE001
            pass

    def _proxy_index(self, code, language="Python"):
        model = self.panel.code_model
        name = "probe_%d" % model.rowCount()
        model.add_asset(code, name, language, "", "", False)
        row = next(r for r in range(model.rowCount()) if model.assets[r].name == name)
        index = self.panel.code_sorted_model.mapFromSource(model.index(row, 0))
        if not index.isValid():
            self.skipTest("the code grid filters the probe out")
        return index, row

    def test_the_buttons_are_the_code_tiles_alone(self):
        self.assertIn("execute", self.panel.code_delegate._badge_clicks)
        self.assertIn("edit", self.panel.code_delegate._badge_clicks)
        self.assertNotIn("edit", self.panel.asset_delegate._badge_clicks,
                         "the Node tiles got the snippet pencil")

    def _click(self, badge, index):
        with mock.patch.object(self.panel, "current_section", "code"):
            self.panel.code_delegate._badge_clicks[badge](index)

    def test_a_failing_run_is_said_with_the_snippets_name(self):
        index, row = self._proxy_index("1 / 0")
        name = self.panel.code_model.assets[row].name
        with mock.patch("amaze.core.debug.refuse") as refuse:
            self._click("execute", index)
        refuse.assert_called_once()
        self.assertIn(name, refuse.call_args[0][0])
        self.assertIn("ZeroDivisionError", refuse.call_args[0][0])

    def test_the_pencil_opens_the_same_editor_as_right_click_edit(self):
        index, row = self._proxy_index("print(1)")
        section = self.panel.sections["code"]
        opened = []
        with mock.patch.object(type(section), "_edit_code_row",
                               lambda _self, r: opened.append(r)):
            self._click("edit", index)
        self.assertEqual([row], opened)


if __name__ == "__main__":
    unittest.main()
