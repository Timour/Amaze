"""The Cancel chip on the Section Tab Strip: shows exactly while the conversion bar shows (one visibility door), its verb is the folder switch's pair in the folder switch's order (flush FIRST, then cancel), and a cancelled folder re-queues on revisit rather than being remembered as missing."""

import ast
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(    # THREE dirnames up = scripts/python, the directory holding the `amaze` package - the DEV tree, not the install on Houdini's path
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # BEFORE the app exists ▸p/first-app-picks-the-platform
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401
from amaze.core import file_library, thumbnails  # noqa: E402
from amaze.helpers import ui_helpers  # noqa: E402
from amaze.tests import test_support  # noqa: E402


def _press(point):
    return QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonPress, point,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier)


class TheCancelVerb(unittest.TestCase):
    """FileFiles.cancel_conversions - the model half, no panel."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="amaze_cancel_")
        self.addCleanup(shutil.rmtree, self.root, True)
        with open(os.path.join(self.root, "tex.exr"), "wb") as handle:    # an EXR is not natively decodable, so it takes the convert path and genuinely queues
            handle.write(b"\x76\x2f\x31\x01" + b"\0" * 256)
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.add_file_folder(self.root)
        self.model = file_library.FileFiles(self.prefs)
        self.addCleanup(thumbnails.engine.cancel_pending_converts)

    def _loaded_keys(self):
        self.model._load([self.root])
        keys = set(self.model._progress_keys)
        self.assertTrue(
            keys, "the fixture queued nothing, so nothing below is "
            "about a running batch")
        return keys

    def test_cancel_leaves_zero_pending_keys(self):
        keys = self._loaded_keys()
        self.model.cancel_conversions()
        self.assertEqual(set(), self.model._progress_keys)
        for key in keys:
            self.assertIsNone(
                thumbnails.engine._states.get(key),
                "a cancelled key must reset to UNREQUESTED - %r is "
                "still %r" % (key, thumbnails.engine._states.get(key)))

    def test_flush_comes_before_cancel(self):
        """Reversing the pair is silent and only costs a re-convert on the next visit, so the ORDER is pinned, not just the calls."""
        self._loaded_keys()
        order = []
        real_cancel = thumbnails.engine.cancel_pending_converts
        self.model._flush_image_cache = (
            lambda why: order.append("flush"))
        thumbnails.engine.cancel_pending_converts = (
            lambda: order.append("cancel"))
        self.addCleanup(setattr, thumbnails.engine,
                        "cancel_pending_converts", real_cancel)
        self.model.cancel_conversions()
        self.assertEqual(["flush", "cancel"], order)

    def test_the_bar_is_settled_not_stranded(self):
        """A cancel has no reload behind it to reset the counters the way a folder switch does, so it must settle the bar itself or the bar waits forever for attempts that were just cancelled."""
        self._loaded_keys()
        seen = []
        self.model.progress_changed.connect(
            lambda done, total: seen.append((done, total)))
        self.model.cancel_conversions()
        self.assertTrue(seen, "cancel emitted no progress at all")
        done, total = seen[-1]
        self.assertGreaterEqual(
            done, total,
            "cancel left the bar stranded at %s/%s" % (done, total))

    def test_a_cancelled_folder_reconverts_on_revisit(self):
        self._loaded_keys()
        self.model.cancel_conversions()
        self.model._load([self.root])
        self.assertGreater(
            self.model._progress_total, 0,
            "the cancelled batch was remembered as MISSING instead of "
            "unrequested, so the revisit queued nothing")


class TheCancelChip(unittest.TestCase):
    """The chip itself, on a bare SectionTabBar."""

    def setUp(self):
        self.tabs = ui_helpers.SectionTabBar(
            [("material", "Material"), ("file", "File")])
        self.tabs.resize(600, self.tabs.HEIGHT)
        self.fired = []
        self.tabs.cancelClicked.connect(lambda: self.fired.append(True))

    def test_a_press_on_the_chip_emits_and_toggles_no_tab(self):
        self.tabs.setChecked("material", emit=False)
        self.tabs.set_cancel_visible(True)
        rect = self.tabs._cancel_rect()
        self.assertIsNotNone(rect, "600px of strip left no room for "
                             "the chip, so the press below hits nothing")
        QtWidgets.QApplication.sendEvent(
            self.tabs, _press(rect.center()))
        self.assertEqual([True], self.fired)
        self.assertEqual("material", self.tabs._checked_key)

    def test_a_hidden_chip_takes_no_press(self):
        self.tabs.set_cancel_visible(True)
        rect = self.tabs._cancel_rect()
        self.tabs.set_cancel_visible(False)
        QtWidgets.QApplication.sendEvent(
            self.tabs, _press(rect.center()))
        self.assertEqual([], self.fired)

    def test_the_chip_centers_on_the_strip_not_the_tray(self):
        """The chip floats OUTSIDE the tray, so the row's full height is its visual reference - tray-centered it sits 2.5px low against the strip."""
        self.tabs.set_cancel_visible(True)
        rect = self.tabs._cancel_rect()
        self.assertIsNotNone(rect)
        self.assertEqual(
            self.tabs.height() / 2.0, rect.center().y(),
            "the chip is not centered on the strip's full height")

    def test_a_press_on_a_tab_still_selects_it(self):
        self.tabs.setChecked("material", emit=False)
        self.tabs.set_cancel_visible(True)
        (_, rect) = self.tabs._chip_rects()[1]
        QtWidgets.QApplication.sendEvent(
            self.tabs, _press(rect.center()))
        self.assertEqual("file", self.tabs._checked_key)
        self.assertEqual([], self.fired)


class TheChipFollowsTheBar(unittest.TestCase):
    """The panel half: one condition, one door, and the wiring."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _file_section_quiet(self):
        """Enter the File section and settle any batch the fixture itself queued, so the bar below is driven by this test alone."""
        panel = self.panel
        if panel._is_online():
            panel.leave_online_world()
        panel.section_tabs.setChecked("file")
        QtWidgets.QApplication.processEvents()
        self.assertEqual("file", panel.current_section)
        panel.file_files_model.cancel_conversions()
        return panel

    def test_the_chip_shows_exactly_when_the_bar_shows(self):
        panel = self._file_section_quiet()
        panel._on_folder_progress("file", 1, 10)
        self.assertFalse(panel.texture_progress.isHidden())
        self.assertTrue(panel.section_tabs.cancel_visible())
        panel._on_folder_progress("file", 10, 10)
        self.assertTrue(panel.texture_progress.isHidden())
        self.assertFalse(panel.section_tabs.cancel_visible())

    def test_the_chip_survives_a_strip_rebuild(self):
        """The strip is torn down and rebuilt on an enabled_sections change or a world flip - mid-batch the new strip must show the chip the old one was showing, READ from the bar itself, never re-derived."""
        panel = self._file_section_quiet()
        panel._on_folder_progress("file", 1, 10)
        panel._build_section_tabs()
        self.assertTrue(
            panel.section_tabs.cancel_visible(),
            "the rebuilt strip forgot the chip mid-batch")
        panel._on_folder_progress("file", 10, 10)
        panel._build_section_tabs()
        self.assertFalse(panel.section_tabs.cancel_visible())

    def test_activation_hides_the_chip_with_the_bar(self):
        panel = self._file_section_quiet()
        panel._on_folder_progress("file", 1, 10)
        panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        self.assertTrue(panel.texture_progress.isHidden())
        self.assertFalse(
            panel.section_tabs.cancel_visible(),
            "activation hid the bar and left the chip up - the two "
            "are one condition and may never disagree")

    def test_the_chip_press_reaches_the_engine(self):
        """The whole chain: press -> hit -> signal -> panel -> model -> engine, with the flush ahead of the cancel."""
        panel = self._file_section_quiet()
        panel._on_folder_progress("file", 1, 10)
        panel.section_tabs.resize(600, panel.section_tabs.HEIGHT)
        rect = panel.section_tabs._cancel_rect()
        self.assertIsNotNone(rect)
        order = []
        model = panel.file_files_model
        real_flush = model._flush_image_cache
        real_cancel = thumbnails.engine.cancel_pending_converts
        model._flush_image_cache = lambda why: order.append("flush")
        thumbnails.engine.cancel_pending_converts = (
            lambda: order.append("cancel"))
        self.addCleanup(setattr, model, "_flush_image_cache", real_flush)
        self.addCleanup(setattr, thumbnails.engine,
                        "cancel_pending_converts", real_cancel)
        QtWidgets.QApplication.sendEvent(
            panel.section_tabs, _press(rect.center()))
        self.assertEqual(
            ["flush", "cancel"], order,
            "the chip's press did not reach the engine through the "
            "flush-first pair")

    def test_the_bar_has_one_visibility_door(self):
        """Source-derived: the bar's setVisible may appear ONCE in the package, inside the door - a second site is a place the chip and the bar can be made to disagree."""
        package_root = os.path.dirname(os.path.dirname(
            os.path.abspath(file_library.__file__)))
        sites = []
        for folder, dirs, files in os.walk(package_root):
            dirs[:] = [d for d in dirs
                       if d not in ("tests", "__pycache__")]
            for name in sorted(files):
                if not name.endswith(".py"):
                    continue
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as handle:
                    text = handle.read()
                for number, line in enumerate(text.splitlines(), 1):
                    if "texture_progress.setVisible" in line:
                        sites.append((os.path.relpath(path, package_root),
                                      number))
        self.assertEqual(
            1, len(sites),
            "the bar's visibility has %d writers, so the chip can be "
            "made to disagree with it: %r" % (len(sites), sites))
        from amaze.panel import panel as panel_mod
        with open(os.path.abspath(panel_mod.__file__),
                  encoding="utf-8") as handle:
            text = handle.read()
        tree = ast.parse(text)
        door = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) \
                    and node.name == "set_conversion_bar_visible":
                door = node
        self.assertIsNotNone(door, "the door itself is gone")
        self.assertTrue(
            door.lineno <= sites[0][1] <= door.end_lineno,
            "the one setVisible site sits outside the door")


if __name__ == "__main__":
    unittest.main()
