"""The Cancel chip shows with the conversion bar, flushes then cancels; cancelled work re-queues."""

import ast
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(    # three dirnames up: the dev tree, not the install
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # BEFORE the app exists ▸p/first-app-picks-the-platform
from PySide6 import QtCore, QtGui, QtWidgets

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


class TheCancelConversionsModel(unittest.TestCase):
    """FileFiles.cancel_conversions - the model part, without a panel."""

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

    def test_the_cancel_completes_the_progress_bar(self):
        """No reload resets the counters after a cancel, so the cancel completes the bar itself."""
        self._loaded_keys()
        seen = []
        self.model.progress_changed.connect(
            lambda done, total: seen.append((done, total)))
        self.model.cancel_conversions()
        self.assertTrue(seen, "cancel emitted no progress at all")
        done, total = seen[-1]
        self.assertGreaterEqual(
            done, total,
            "cancel left the bar unfinished at %s/%s" % (done, total))

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

    def test_a_hidden_chip_ignores_a_press(self):
        self.tabs.set_cancel_visible(True)
        rect = self.tabs._cancel_rect()
        self.tabs.set_cancel_visible(False)
        QtWidgets.QApplication.sendEvent(
            self.tabs, _press(rect.center()))
        self.assertEqual([], self.fired)

    def test_the_chip_centers_on_the_strip_above_its_line_not_the_tray(self):
        """The chip is drawn outside the tray, so it centers on the row above the bottom line."""
        self.tabs.set_cancel_visible(True)
        rect = self.tabs._cancel_rect()
        self.assertIsNotNone(rect)
        self.assertEqual(
            self.tabs.LINE_TOP / 2.0, rect.center().y(),
            "the chip is not centered on the strip above its bottom line")

    def test_a_press_on_a_tab_still_selects_it(self):
        self.tabs.setChecked("material", emit=False)
        self.tabs.set_cancel_visible(True)
        (_, rect) = self.tabs._chip_rects()[1]
        QtWidgets.QApplication.sendEvent(
            self.tabs, _press(rect.center()))
        self.assertEqual("file", self.tabs._checked_key)
        self.assertEqual([], self.fired)


class TheChipIsShownWithTheProgressBar(unittest.TestCase):
    """The panel part: one condition, one `set_conversion_bar_visible`, and the signals."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _file_section_with_no_batch_running(self):
        """Enter the File section and settle any batch the fixture queued."""
        panel = self.panel
        if panel._is_online():
            panel.leave_online_mode()
        panel.section_tabs.setChecked("file")
        QtWidgets.QApplication.processEvents()
        self.assertEqual("file", panel.current_section)
        panel.file_files_model.cancel_conversions()
        return panel

    def test_the_chip_shows_exactly_when_the_bar_shows(self):
        panel = self._file_section_with_no_batch_running()
        panel._on_file_folder_progress(1, 10)
        self.assertFalse(panel.texture_progress.isHidden())
        self.assertTrue(panel.section_tabs.cancel_visible())
        panel._on_file_folder_progress(10, 10)
        self.assertTrue(panel.texture_progress.isHidden())
        self.assertFalse(panel.section_tabs.cancel_visible())

    def test_the_chip_is_kept_through_a_strip_rebuild(self):
        """A rebuilt tab strip reads the chip state from the bar itself, never recomputing it."""
        panel = self._file_section_with_no_batch_running()
        panel._on_file_folder_progress(1, 10)
        panel._build_section_tabs()
        self.assertTrue(
            panel.section_tabs.cancel_visible(),
            "the rebuilt strip hid the chip during a batch")
        panel._on_file_folder_progress(10, 10)
        panel._build_section_tabs()
        self.assertFalse(panel.section_tabs.cancel_visible())

    def test_activation_hides_the_chip_with_the_bar(self):
        panel = self._file_section_with_no_batch_running()
        panel._on_file_folder_progress(1, 10)
        panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        self.assertTrue(panel.texture_progress.isHidden())
        self.assertFalse(
            panel.section_tabs.cancel_visible(),
            "activation hid the bar and left the chip visible - the two "
            "follow one condition and must always match")

    def test_the_chip_press_cancels_the_engine(self):
        """Press, hit test, `cancelClicked`, panel, model, engine; the flush before the cancel."""
        panel = self._file_section_with_no_batch_running()
        panel._on_file_folder_progress(1, 10)
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
            "the chip's press did not reach the engine as a flush "
            "followed by a cancel")

    def test_the_bar_has_one_visibility_setter(self):
        """Source scan: the bar's `setVisible` appears once, inside `set_conversion_bar_visible`."""
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
        setter = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) \
                    and node.name == "set_conversion_bar_visible":
                setter = node
        self.assertIsNotNone(setter, "set_conversion_bar_visible is gone")
        self.assertTrue(
            setter.lineno <= sites[0][1] <= setter.end_lineno,
            "the one setVisible call is outside set_conversion_bar_visible")


if __name__ == "__main__":
    unittest.main()
