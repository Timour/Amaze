"""Panel and UI correctness: one route per question, not three."""

import ast
import json
import os
import re
import shutil
import sys
import tempfile
import types
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtTest, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import file_library, folders, geo_library  # noqa: E402
from amaze.core import grid_columns  # noqa: E402
from amaze.core import keyed_store, locations, notes, tile_icons  # noqa: E402
from amaze.prefs import prefs as prefs_mod  # noqa: E402
from amaze.helpers import theme, ui_helpers  # noqa: E402
from amaze.tests import test_support  # noqa: E402


def _location_prefs(case, names, colors, show_all, recursive):
    """Only what a location record composes; a real `Prefs` finds the install."""
    prefs = prefs_mod.Prefs.__new__(prefs_mod.Prefs)
    prefs.save = lambda: None
    prefs._directory = tempfile.mkdtemp(prefix="amaze_locations_")
    prefs._library_user = test_support.FIXTURE_USER
    prefs.data = {}
    prefs._file_folders = []
    prefs._file_favorites = []
    prefs._file_location_records = {}
    for path in set(names) | set(colors) | set(show_all) | set(recursive):
        prefs._file_folders.append(path)
        record = prefs._file_location_records.setdefault(
            path, {"registered": True})
        if path in names:
            record["name"] = names[path]
        if path in colors:
            record["color"] = colors[path]
        if path in show_all:
            record["show_all"] = show_all[path]
        if path in recursive:
            record["recursive"] = True
    locations.forget()
    locations.migrate(prefs)
    case.addCleanup(shutil.rmtree, prefs._directory, True)
    case.addCleanup(keyed_store.release)
    case.addCleanup(locations.forget)
    return prefs

PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def source_of(relative):
    with open(os.path.join(PACKAGE, relative), encoding="utf-8") as handle:
        return handle.read()


def method_source(relative, class_name, name):
    """One method's source, scoped to its class, never the base stub."""
    text = source_of(relative)
    tree = ast.parse(text)
    lines = text.splitlines()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == class_name):
            continue
        for child in node.body:
            if isinstance(child, ast.FunctionDef) and child.name == name:
                return "\n".join(lines[child.lineno - 1:child.end_lineno])
    raise AssertionError(
        "no %s.%s in %s" % (class_name, name, relative))


def func_source(relative, name):
    """One function's source, by AST rather than by slicing on text."""
    text = source_of(relative)
    tree = ast.parse(text)
    lines = text.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return "\n".join(lines[node.lineno - 1:node.end_lineno])
    raise AssertionError("no function %r in %s" % (name, relative))


class _PanelCase(unittest.TestCase):
    """A real panel on a fixture library, built only by `fixture_panel`."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    @classmethod
    def tearDownClass(cls):
        try:
            test_support.stop_panel_workers(cls.panel)
        except Exception:                                 # noqa: BLE001
            pass


class EveryAssetSidebarFollowsItsFilter(unittest.TestCase):
    """A category can never show a count it cannot deliver."""

    def test_all_three_sections_share_one_apply_filter(self):
        """The push into the category model is what the sidebar counts on."""
        from amaze.panel import sections
        for name in ("CopSection", "CodeSection", "MaterialSection"):
            cls = getattr(sections, name)
            self.assertNotIn(
                "apply_filter", cls.__dict__,
                "%s overrides apply_filter again - the sidebar push "
                "belongs to the shared route, or two of the three "
                "sections silently do not get it" % name)

    def test_the_shared_route_pushes_into_the_sections_own_model(self):
        """By AST: a text search matches `apply_filter`'s own docstring."""
        self.assertTrue(
            self._calls("panel/sections.py", "AssetSection", "apply_filter",
                        "set_renderer_filter"),
            "the shared apply_filter no longer CALLS set_renderer_filter, "
            "so the sidebar can disagree with the grid again")

    @staticmethod
    def _calls(relative, class_name, method, callee) -> bool:
        text = source_of(relative)
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.ClassDef)
                    and node.name == class_name):
                continue
            for child in node.body:
                if not (isinstance(child, ast.FunctionDef)
                        and child.name == method):
                    continue
                for call in ast.walk(child):
                    if not isinstance(call, ast.Call):
                        continue
                    func = call.func
                    name = getattr(func, "attr", getattr(func, "id", ""))
                    if name == callee:
                        return True
        return False

    def test_the_preference_reaches_every_sidebar(self):
        """By AST: the preference reached two of the three proxies."""
        self.assertTrue(
            self._calls("panel/panel.py", "AmazePanel",
                        "_prefs_dialog_closed", "sidebar_proxies"),
            "the Preferences push enumerates the proxies by hand "
            "again - the enumeration that was short is exactly how "
            "Code was missed")

    def _panel(self):
        panel = test_support.fixture_panel(self)
        panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        return panel

    def test_a_filter_and_a_preferences_close_fall_back_once(self):
        """The sidebar refresh ends in the fall-back to All; its callers do not repeat it."""
        from unittest import mock
        panel = self._panel()
        for name, act in (
                ("filter", lambda: panel._section().apply_filter(None)),
                ("preferences", lambda: panel._prefs_dialog_closed(panel.prefs.dir))):
            with self.subTest(name), \
                    mock.patch.object(panel, "_refresh_sidebar_categories",
                                      wraps=panel._refresh_sidebar_categories) as refresh, \
                    mock.patch.object(panel, "_ensure_sidebar_selection",
                                      wraps=panel._ensure_sidebar_selection) as ensure:
                act()
                self.assertTrue(refresh.call_count, "premise: the sidebar refreshed")
                self.assertEqual(refresh.call_count, ensure.call_count)

    def test_the_refresh_drops_every_sidebars_counts(self):
        """Each sidebar proxy's own category model, the four of them."""
        from unittest import mock
        panel = self._panel()
        models = [getattr(panel, name) for name in (
            "category_model", "cop_category_model", "code_category_model",
            "gradient_categories_model")]
        patches = [mock.patch.object(model, "drop_count_cache") for model in models]
        dropped = [patch.start() for patch in patches]
        try:
            panel._refresh_sidebar_categories()
        finally:
            for patch in patches:
                patch.stop()
        self.assertEqual([1, 1, 1, 1], [drop.call_count for drop in dropped])

    def test_sidebar_proxies_names_all_four(self):
        from amaze.panel import panel as panel_mod
        self.assertEqual(
            {"material", "cop", "code", "gradient"},
            set(panel_mod.AmazePanel.SIDEBAR_PROXY_ATTRS),
            "a section gained or lost a sidebar proxy without the "
            "one list that every push walks")


class ACategoryIsActedOnByItsStoredName(_PanelCase):
    """`Categories.data` strips a leading underscore for `DisplayRole`."""

    def test_the_panel_reads_the_stored_name(self):
        model = self.panel.category_model
        model.check_add_category("_WIP")
        row = -1
        for i in range(model.rowCount()):
            if model.data(model.index(i, 0), model.CatSortRole) == "_WIP":
                row = i
                break
        self.assertGreaterEqual(
            row, 0, "could not create a category stored with a leading "
                    "underscore - the premise is gone, not the subject")
        index = model.index(row, 0)
        self.assertEqual(
            "WIP", index.data(QtCore.Qt.ItemDataRole.DisplayRole),
            "the sidebar no longer strips the underscore - this test "
            "can no longer see its subject")
        self.assertEqual(
            "_WIP", self.panel._raw_category_name(index),
            "the panel reads the DISPLAYED name, so Rename matches no "
            "asset and silently does nothing, Remove returns early and "
            "leaves the row, and a drop creates a SECOND category "
            "beside it and files the asset under that")

    def test_every_acting_site_goes_through_the_helper(self):
        """A category acts on the name it stores, through `sidebar_key`."""
        for name in ("droppable_index", "category_at_point"):
            source = func_source("panel/sidebar.py", name)
            self.assertIn(
                "_raw_category_name", source,
                "%s reads a category name without the helper - a "
                "fourth site getting this wrong is what the helper "
                "exists to stop" % name)

        self.assertIn(
            "_raw_category_name",
            method_source("panel/sections.py", "AssetSection",
                          "sidebar_key"),
            "AssetSection.sidebar_key stopped reading the helper, so "
            "every sidebar verb behind it now acts on the DISPLAYED "
            "name")
        for verb in ("menu_rename_category", "menu_remove_category"):
            self.assertIn(
                "sidebar_key",
                method_source("panel/sections.py", "AssetSection", verb),
                "%s reads a category name without going through "
                "sidebar_key" % verb)

    def test_one_answer_for_the_selected_category(self):
        """One fallback to `live_current_index`, or the dialogs disagree."""
        source = source_of("panel/panel.py")
        self.assertEqual(
            1, source.count("def _selected_category_name"),
            "the shared answer is gone or duplicated")
        self.assertIn(
            "_selected_category_name",
            func_source("panel/panel.py", "_current_code_category"),
            "_current_code_category answers 'which category is selected' "
            "on its own again")
        for cls in ("MaterialSection", "CopSection"):
            self.assertIn(
                "_selected_category_name",
                method_source("panel/sections.py", cls, "save_categories"),
                "%s answers 'which category is selected' on its own "
                "again" % cls)


class CaptureIsDecidedInOnePlace(unittest.TestCase):

    def test_the_tile_menu_does_not_re_decide(self):
        """The policy is only that the target is the current scene."""
        source = func_source("panel/sections.py", "menu_capture_enabled")
        self.assertIn(
            "current_scene_path", source,
            "the gate no longer tests the thing the capture is filed "
            "against")


class TheMapNamesEveryModule(unittest.TestCase):
    """The map names every module; `SHORTHAND` are the ones named by phrase."""

    SHORTHAND = {"helpers/theme.py", "helpers/helpers.py",
                 "helpers/vex_syntax.py"}

    @staticmethod
    def _brace_paths(body):
        """Expand `core/{texture,geo}_library.py` into real paths."""
        paths = set()
        for match in re.finditer(r"([\w/]+)/\{([^}]*)\}([\w.]*)", body):
            head, alternatives, tail = match.groups()
            for alternative in alternatives.split(","):
                paths.add("%s/%s%s" % (head, alternative.strip(), tail))
        return paths

    def test_the_map_places_every_module_in_its_directory(self):
        """`dir/stem`, never the bare stem: prose about a word satisfies that."""
        repo = os.path.dirname(os.path.dirname(os.path.dirname(PACKAGE)))
        overview = os.path.join(repo, "docs", "architecture", "overview.md")
        if not os.path.exists(overview):
            self.fail("the system map is missing: %s" % overview)
        with open(overview, encoding="utf-8") as handle:
            body = handle.read()
        braces = self._brace_paths(body)
        missing = []
        for root, dirs, files in os.walk(PACKAGE):
            dirs[:] = [d for d in dirs
                       if d != "__pycache__" and d != "tests"]
            for name in files:
                if not name.endswith(".py") or name == "__init__.py":
                    continue
                rel = test_support.posix_relpath(
                    os.path.join(root, name), PACKAGE)
                if rel in self.SHORTHAND or rel in braces:
                    continue
                if rel[:-3] in body:          # dir/stem, extension free
                    continue
                missing.append(rel)
        self.assertEqual(
            [], sorted(missing),
            "the system map does not place these modules in the "
            "directory they are in, so anyone reading it to find where "
            "something lives is sent to the wrong place or nowhere: %s"
            % ", ".join(sorted(missing)))



def _material(test, name):
    """A real Karma material in /mat - the save door asks the node what it is."""
    import hou
    node = hou.node("/mat").createNode("subnet", name)
    node.createNode("mtlxstandard_surface")
    test.addCleanup(node.destroy)
    return node


class TheSaveDialogOffersEveryCategory(unittest.TestCase):
    """The dropdown's list comes from the one category-names home - a name-anchored filter once dropped every category merely STARTING with the pseudo-category's name."""

    def test_a_category_starting_with_All_is_offered(self):
        from unittest import mock

        from amaze.panel import panel as panel_mod
        panel = test_support.fixture_panel(self)
        panel.category_model.check_add_category("Alloys")
        offered = {}

        class _Dialog:
            canceled = True
            categories = ""

            def __init__(self, cats, current, name="", name_enabled=True,
                         parent=None, **_section_rows):
                offered["cats"] = list(cats)

            def exec(self):
                return 0

        with mock.patch.object(panel_mod.save_dialog, "SaveDialog",
                               _Dialog):
            panel.get_material_info_user([_material(self, "alloy_mat")])
        self.assertIn(
            "Alloys", offered.get("cats", []),
            "a category starting with the pseudo-category's name is "
            "missing from the save dialog's dropdown")


class TheMaterialSaveOffersANameOnlyWhenOneWillDo(unittest.TestCase):
    """ROADMAP R56: one save engine. A single material may be renamed on the way in; several share one dialog, so the field greys and each keeps its node's name."""

    def _asked(self, selection):
        """(name, name_enabled) the save dialog was built with."""
        from unittest import mock

        from amaze.panel import panel as panel_mod
        panel = test_support.fixture_panel(self)
        seen = {}

        class _Dialog:
            canceled = True
            categories = ""

            def __init__(self, cats, current, name="", name_enabled=True,
                         parent=None, **_section_rows):
                seen["name"] = name
                seen["enabled"] = name_enabled

            def exec(self):
                return 0

        with mock.patch.object(panel_mod.save_dialog, "SaveDialog",
                               _Dialog):
            panel.get_material_info_user(selection)
        return seen.get("name"), seen.get("enabled")

    def _node(self, name):
        return _material(self, name)

    def test_one_material_prefills_its_own_name(self):
        self.assertEqual(("rocks1", True), self._asked([self._node("rocks1")]))

    def test_several_materials_grey_the_field(self):
        self.assertEqual(
            ("", False),
            self._asked([self._node("a"), self._node("b")]),
            "a multi-selection was offered a live Name field, so one "
            "typed name would land on every material saved")


class GridResolvesTheDelegateThroughTheModule(unittest.TestCase):

    def test_no_module_level_delegate_binding(self):
        """The dev-reload chain reloads grid BEFORE delegates, so a module-level binding keeps the previous session's class - every use goes through \x60delegates.\x60, which the reload rebinds."""
        source = source_of("panel/grid.py")
        self.assertNotIn(
            "\nAssetItemDelegate =", source,
            "grid.py binds the delegate at import time - under "
            "AMAZE_DEV_RELOAD the reopened panel sizes and colours "
            "tiles from the previous session's class")


class AClickLeavesTheConfiguredStepsAlone(unittest.TestCase):
    """The jump-sized step is for one jump - left in place, a press on the handle (distance 0) zeroes both steps and kills the wheel and arrow keys over the slider."""

    def test_a_handle_press_does_not_zero_the_steps(self):
        slider = ui_helpers.ClickSlider()
        slider.setOrientation(QtCore.Qt.Orientation.Horizontal)
        slider.setRange(64, 512)
        slider.setValue(128)
        slider.resize(200, 24)
        slider.setSingleStep(50)
        slider.setPageStep(50)
        slider._apply_mouse_value(slider._x_for_value(slider.value()))
        self.assertEqual(
            (50, 50), (slider.singleStep(), slider.pageStep()),
            "the press clobbered the configured steps with the click "
            "distance - a handle press leaves them 0")


class StepSizeKeepsTheSliderOnItsMarks(unittest.TestCase):
    """Step Size on: a click, a key and a wheel notch each land on a snap mark."""

    def _slider(self, stepped=True):
        slider = ui_helpers.ClickSlider()
        slider.setOrientation(QtCore.Qt.Orientation.Horizontal)
        slider.setRange(64, 512)
        slider.setValue(128)
        slider.resize(200, 24)
        slider.setSingleStep(50)
        slider.setPageStep(50)
        slider.stepped = stepped
        slider.show()
        self.addCleanup(slider.close)
        return slider

    @staticmethod
    def _wheel(slider, dy):
        point = QtCore.QPointF(50, 12)
        QtWidgets.QApplication.sendEvent(slider, QtGui.QWheelEvent(
            point, slider.mapToGlobal(point), QtCore.QPoint(0, 0), QtCore.QPoint(0, dy),
            QtCore.Qt.MouseButton.NoButton, QtCore.Qt.KeyboardModifier.NoModifier,
            QtCore.Qt.ScrollPhase.NoScrollPhase, False))

    def test_a_click_between_marks_lands_on_the_nearest(self):
        slider = self._slider()
        slider._apply_mouse_value(slider._x_for_value(200))
        self.assertEqual(192, slider.value(), "a click at 200 did not land on 192")
        slider._apply_mouse_value(slider._x_for_value(140))
        self.assertEqual(128, slider.value(), "a click at 140 did not land on 128")

    def test_keys_step_from_mark_to_mark(self):
        slider = self._slider()
        steps = []
        for key in (QtCore.Qt.Key.Key_Right, QtCore.Qt.Key.Key_End,
                    QtCore.Qt.Key.Key_Right, QtCore.Qt.Key.Key_Left,
                    QtCore.Qt.Key.Key_Home):
            QtTest.QTest.keyClick(slider, key)
            steps.append(slider.value())
        self.assertEqual([192, 512, 512, 448, 64], steps)

    def test_a_wheel_notch_is_one_mark_and_half_notches_add_up(self):
        slider = self._slider()
        steps = []
        for dy in (120, 60, 60, -120):
            self._wheel(slider, dy)
            steps.append(slider.value())
        self.assertEqual([192, 192, 256, 192], steps)

    def test_the_two_ends_are_stops_without_a_dot(self):
        slider = self._slider()
        self.assertEqual((128, 192, 256, 320, 384, 448), slider.drawn_marks())
        self.assertEqual((64, 512), (min(slider.snap_marks), max(slider.snap_marks)))

    def test_off_the_slider_moves_freely(self):
        slider = self._slider(stepped=False)
        QtTest.QTest.keyClick(slider, QtCore.Qt.Key.Key_Right)
        self.assertEqual(178, slider.value(), "a key no longer moves by the single step")
        slider._apply_mouse_value(slider._x_for_value(200))
        self.assertEqual(200, slider.value(), "a click between marks was moved")

    def test_a_size_between_marks_opens_on_the_nearest(self):
        from amaze.panel import grid
        prefs = types.SimpleNamespace(view_mode="grid", thumbsize=200, step_size=True)
        panel = types.SimpleNamespace(prefs=prefs, LIST_THUMB_SIZE=16)
        self.assertEqual(192, grid.active_thumbsize(panel))
        prefs.step_size = False
        self.assertEqual(200, grid.active_thumbsize(panel))


class ASelfPaintedWidgetDimsWhenDisabled(unittest.TestCase):
    """Qt does not dim a pixmap a widget paints itself; each does it by hand."""

    def test_the_slider_paints_differently_when_disabled(self):
        slider = ui_helpers.ClickSlider()
        slider.setOrientation(QtCore.Qt.Orientation.Horizontal)
        slider.setRange(64, 512)
        slider.setValue(128)
        slider.resize(200, 24)

        def rendered(enabled):
            slider.setEnabled(enabled)
            image = QtGui.QImage(slider.size(),
                                 QtGui.QImage.Format.Format_ARGB32)
            image.fill(QtGui.QColor(0, 0, 0, 0))
            slider.render(image)
            return image

        self.assertNotEqual(
            rendered(True), rendered(False),
            "the size slider paints identically enabled and disabled - "
            "in LIST mode it looks live, ignores every click because Qt "
            "withholds mouse events, and reads as broken")

    def test_a_disabled_toggle_switch_neither_shines_nor_beckons(self):
        """The Customize dialog greys its Light Icon switch - painted at full strength with a pointing hand, it reads as a live control that ignores clicks."""
        switch = ui_helpers.ToggleSwitch("Light Icon")
        switch.resize(switch.sizeHint())

        def rendered(enabled):
            switch.setEnabled(enabled)
            image = QtGui.QImage(switch.size(),
                                 QtGui.QImage.Format.Format_ARGB32)
            image.fill(QtGui.QColor(0, 0, 0, 0))
            switch.render(image)
            return image

        self.assertNotEqual(rendered(True), rendered(False),
                            "the switch paints identically enabled "
                            "and disabled")
        switch.setEnabled(False)
        self.assertNotEqual(
            QtCore.Qt.CursorShape.PointingHandCursor,
            switch.cursor().shape(),
            "a disabled switch still shows the pointing hand")
        switch.setEnabled(True)
        self.assertEqual(QtCore.Qt.CursorShape.PointingHandCursor,
                         switch.cursor().shape())

    def test_both_hand_painted_toolbar_widgets_use_the_shared_rule(self):
        source = source_of("helpers/ui_helpers.py")
        tree = ast.parse(source)
        applies = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if node.name not in ("ChipToggleButton", "IconMenuButton",
                                 "ClickSlider", "ToggleSwitch"):
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.FunctionDef) and \
                        child.name == "paintEvent":
                    applies[node.name] = "apply_disabled_opacity" in \
                        ast.dump(child)
        self.assertEqual(
            {"ChipToggleButton": True, "IconMenuButton": True,
             "ClickSlider": True, "ToggleSwitch": True}, applies,
            "a self-painted widget skips the shared disabled rule - "
            "online, that means two chips dim and one stays bright "
            "while ignoring clicks")

    def test_chip_art_is_rendered_for_the_size_it_is_drawn_at(self):
        source = func_source("helpers/ui_helpers.py", "set_art")
        self.assertIn(
            "self._icon_size * self.RENDER_SCALE", source,
            "set_art rasterises at a literal 16 again, so a chip built "
            "with any other icon_size gets art with no headroom - the "
            "soft-upscaled look RENDER_SCALE exists to prevent")


class NodeAndCodeDoNotBorrowTheVersionColumn(unittest.TestCase):

    def test_they_get_a_delegate_without_the_version_roles(self):
        """A column exists if the section's declared delegate carries its role."""
        import importlib

        sections = importlib.import_module("amaze.panel.sections")
        self.assertEqual("asset_delegate", sections.CopSection.delegate_attr,
                         "Node points the grid at the Materials delegate")
        self.assertEqual("code_delegate", sections.CodeSection.delegate_attr,
                         "Code lost its own delegate, and with it the Run button")
        self.assertEqual("thumb_delegate",
                         sections.MaterialSection.delegate_attr,
                         "Materials lost its own delegate")
        self.assertEqual("gradient_delegate",
                         sections.GradientSection.delegate_attr,
                         "Color lost its own delegate")

    def test_the_shared_delegate_carries_no_version_role(self):
        source = source_of("panel/panel.py")
        tree = ast.parse(source)
        version_roles = {}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Assign) and node.targets):
                continue
            target = node.targets[0]
            if not (isinstance(target, ast.Attribute)
                    and target.attr in ("thumb_delegate", "asset_delegate",
                                        "code_delegate")):
                continue
            version_roles[target.attr] = any(
                kw.arg in ("versions_role", "active_version_role")
                for kw in getattr(node.value, "keywords", []))
        self.assertEqual(
            {"thumb_delegate": True, "asset_delegate": False,
             "code_delegate": False}, version_roles,
            "the Node/Code delegate carries the version roles, so those "
            "two sections paint a Version column again")

    def test_the_badge_hover_reads_the_active_delegate(self):
        source = func_source("panel/panel.py", "_sync_badge_hover")
        self.assertIn(
            "self.thumblist.itemDelegate()", source,
            "the hover hit-test hard-codes the Materials delegate, "
            "which is no longer the one painting in Node or Code")


class TheOnlineGridIsFittedLikeTheOthers(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def test_a_column_is_its_DEFAULT_whenever_the_rows_land(self):
        """`COLUMN_DEFAULT_WIDTH` before and after a reset; nothing measures."""
        panel = self.panel
        panel.section_tabs.setChecked("material")
        panel.prefs.view_mode = "list"
        panel.apply_view_mode()
        self.addCleanup(panel.apply_view_mode)
        self.addCleanup(setattr, panel.prefs, "view_mode", "grid")
        panel.show()
        self.addCleanup(panel.hide)
        QtWidgets.QApplication.processEvents()
        table = panel.thumbtable
        column = grid_columns.KEYS.index("name")
        before = table.columnWidth(column)
        model = panel.material_model
        self.assertTrue(model.rowCount(), "no rows to widen")
        long_name = "a_material_with_a_very_long_name_indeed_x40"
        record = model._assets[0]
        original = record.name
        self.addCleanup(setattr, record, "name", original)
        model.beginResetModel()
        record.name = long_name
        model.endResetModel()
        for _ in range(4):
            QtWidgets.QApplication.processEvents()
        self.assertEqual(
            long_name,
            model.index(0, column).data(QtCore.Qt.ItemDataRole.DisplayRole),
            "the setup did not reach the Name column - not a test")
        self.assertEqual(
            before, table.columnWidth(column),
            "the Name column changed width because rows landed - its "
            "width must not depend on WHEN the model fills")
        self.assertEqual(
            theme.ui_px(panel.COLUMN_DEFAULT_WIDTH["name"]),
            table.columnWidth(column),
            "the Name column is not at its documented default")


class EveryColumnIsCoveredByTheTablesHangingOffIt(unittest.TestCase):
    """A column missing from a table does not raise, it arrives half-configured."""

    def test_every_column_has_a_default_width(self):
        from amaze.panel import panel as panel_mod
        from amaze.core import grid_columns

        missing = set(grid_columns.KEYS) - set(
            panel_mod.AmazePanel.COLUMN_DEFAULT_WIDTH)
        self.assertEqual(
            set(), missing,
            "these columns have no default width, so they take Qt's: "
            "%s" % sorted(missing))

    def test_every_column_is_named_in_the_roles_table(self):
        """From source: the table is a local inside `sync_table_columns`."""
        import ast
        import inspect

        from amaze.core import grid_columns
        from amaze.panel import grid as grid_mod

        keys = set(grid_columns.KEYS)
        listed = set()
        for node in ast.walk(ast.parse(
                inspect.getsource(grid_mod.sync_table_columns))):
            if isinstance(node, ast.Dict) and node.keys:
                names = [k.value for k in node.keys
                         if isinstance(k, ast.Constant)
                         and isinstance(k.value, str)]
                if names and set(names) <= keys:
                    listed |= set(names)
        self.assertTrue(
            listed, "no per-column table was found, so this is vacuous")
        missing = keys - listed
        self.assertEqual(
            set(), missing,
            "these columns are in no roles entry, so they are shown "
            "unconditionally: %s" % sorted(missing))

    def test_every_tick_column_exists(self):
        from amaze.core import grid_columns

        self.assertLessEqual(
            set(grid_columns.GridColumnsMixin.TICK_COLUMNS),
            set(grid_columns.KEYS),
            "a tick column names a column that does not exist")


class OneProgressBarOwnerPerThingShown(unittest.TestCase):

    def test_the_folder_bar_is_hidden_in_the_online_world(self):
        """`current_section` still names the local section in the online world."""
        source = func_source("panel/panel.py", "_on_file_folder_progress")
        self.assertIn(
            "_is_online()", source,
            "a conversion batch started in a File folder draws its bar "
            "over the ONLINE grid, shifting every tile down and up")

    def test_the_geometry_pass_does_not_hide_a_running_conversion(self):
        source = func_source("core/file_library.py", "_render_geo_misses")
        self.assertIn(
            "_progress_keys", source,
            "the geometry pass emits its terminal (0, 0) unconditionally, "
            "hiding the bar while the image conversions it interleaves "
            "with are still running")

    def test_an_interrupt_before_the_first_render_leaves_no_unbound_name(self):
        """An ESC on the first progress tick reaches the finally with the loop never entered, so the scratch path must exist before the try."""
        source = func_source("core/file_library.py", "_render_geo_misses")
        self.assertIn('tmp_path = ""', source,
                      "nothing binds the scratch path before the try - "
                      "a first-tick interrupt turns into a NameError "
                      "raised out of the finally")
        self.assertLess(source.index('tmp_path = ""'),
                        source.index("InterruptableOperation"))

    def test_a_pass_of_only_CACHES_opens_no_progress_bar(self):
        """The bar opens when the pass starts, so caches leave the list first."""
        source = func_source("core/file_library.py", "_render_geo_misses")
        filtered = source.index("is_cache")
        self.assertLess(
            filtered, source.index("total = len(misses)"),
            "caches are filtered after the total is taken, so a pass "
            "of nothing but caches still opens a progress bar")
        self.assertLess(
            filtered, source.index("InterruptableOperation"),
            "caches are filtered after the bar is opened")

    def test_what_counts_as_a_cache_is_the_FILE_CACHE_SOPs_own_output(self):
        """Two extensions, longest-wins, or `.bgeo.sc` reads as `.bgeo`."""
        self.assertTrue(geo_library.is_cache("a.filecache1_v1.0001.bgeo.sc"))
        self.assertTrue(geo_library.is_cache("smoke_v2.0004.vdb"))
        self.assertFalse(
            geo_library.is_cache("hand_saved_asset.bgeo"),
            "a plain .bgeo is what a single saved asset is - it keeps "
            "its thumbnail")
        for other in ("m.abc", "m.usd", "m.obj", "m.geo"):
            with self.subTest(name=other):
                self.assertFalse(geo_library.is_cache(other))


class LocateFolderKeepsEveryPerLocationSetting(unittest.TestCase):
    """A relocate names the prefix; the store registry walks itself."""

    def test_no_caller_enumerates_the_per_location_surfaces(self):
        self.assertFalse(
            hasattr(file_library.FileFolders, "PATH_KEYED_DICTS"),
            "the caller-held enumeration is back - that is the shape "
            "that dropped the colour and the Show All Files override")
        source = func_source("core/file_library.py", "_on_folder_relocated")
        for key in ("file_folder_names", "file_folder_colors",
                    "file_folder_show_all", "file_recursive_folders"):
            self.assertNotIn(
                key, source,
                "the relocate names %s by hand again" % key)

    def test_the_record_names_every_field_once(self):
        """Every field is named once, where the record is defined."""
        self.assertEqual(
            ("registered", "name", "color", "show_all", "recursive"),
            locations.FIELDS,
            "a per-location fact is missing from the one list that "
            "defines a location's record")

    def test_a_relocate_carries_them(self):
        prefs = _location_prefs(self, {"/old/": "Bokeh"}, {"/old/": "#ff8000"},
                                {"/old/": True}, ["/old/"])
        model = file_library.FileFolders.__new__(file_library.FileFolders)
        model.preferences = prefs
        locations.relocate_record(prefs, "/old/", "/new/")    # the product order: the identity's path edit first, then the hook for path-keyed stragglers
        model._on_folder_relocated("/old/", "/new/")
        # Against the record: the derived dicts would read back this seed.
        self.assertEqual({}, locations.record(prefs, "/old/"),
                         "the old path kept its record after the move")
        self.assertEqual(
            {"registered": True, "name": "Bokeh", "color": "#ff8000",
             "show_all": True, "recursive": True},
            locations.record(prefs, "/new/"),
            "a per-location fact did not survive Locate Folder - the "
            "colour and the Show All Files override are the two that "
            "were added after the hook was written")

    def test_a_relocate_carries_the_comments_and_the_tile_icons_too(self):
        """Comments and icons key on the path, so a relocate must carry them."""
        prefs = _location_prefs(self, {}, {}, {}, [])
        keyed_store.release()

        self.assertTrue(notes.set_note(
            prefs, notes.note_key("file", "/old/shot.exr"),
            [{"t": "text", "text": "check the gamma"}]))
        self.assertTrue(tile_icons.set_override(
            prefs, "/old/shot.exr", {"name": "box", "bg": "#ef8878"}))

        model = file_library.FileFolders.__new__(file_library.FileFolders)
        model.preferences = prefs
        model._on_folder_relocated("/old/", "/new/")

        self.assertTrue(
            notes.has_note(prefs, notes.note_key("file", "/new/shot.exr")),
            "the comment was orphaned on the old path")
        self.assertFalse(
            notes.has_note(prefs, notes.note_key("file", "/old/shot.exr")),
            "the comment was copied rather than moved")
        self.assertEqual(
            "box",
            tile_icons.override_for(prefs, "/new/shot.exr").get("name"),
            "the tile icon was orphaned on the old path")

    def test_an_asset_note_is_NOT_dragged_along_by_a_folder_move(self):
        """`notes.json` mixes ids with paths; a folder move touches paths."""
        prefs = _location_prefs(self, {}, {}, {}, [])
        keyed_store.release()

        key = notes.note_key("material", "/old/thing")
        self.assertTrue(notes.set_note(
            prefs, key, [{"t": "text", "text": "not a path"}]))
        model = file_library.FileFolders.__new__(file_library.FileFolders)
        model.preferences = prefs
        model._on_folder_relocated("/old/", "/new/")
        self.assertTrue(
            notes.has_note(prefs, key),
            "an asset key that merely LOOKS like a path was rewritten "
            "by a folder move")

    def test_removing_a_location_takes_all_four_with_it(self):
        """A removal takes every field, or re-adding the folder inherits them."""
        prefs = _location_prefs(self, {"/gone/": "Bokeh"}, {"/gone/": "#ff8000"},
                                {"/gone/": True}, ["/gone/"])
        keyed_store.retire_prefix(prefs, "/gone/")
        self.assertEqual(
            {}, locations.record(prefs, "/gone/"),
            "a per-location fact came back with the path - the colour "
            "and the Show All Files override are the two that used to")

    def test_a_sibling_folder_is_not_captured(self):
        """`/a/tex` must not take `/a/textures` with it."""
        prefs = _location_prefs(self, {"/a/tex/": "one", "/a/textures/": "two"},
                                {}, {}, [])
        keyed_store.retire_prefix(prefs, "/a/tex/")
        self.assertEqual({}, locations.record(prefs, "/a/tex/"),
                         "the location itself was not retired")
        self.assertEqual("two", locations.record(
            prefs, "/a/textures/").get("name"),
            "a sibling whose name merely starts the same was retired too")


class ThereIsOneFontTable(unittest.TestCase):
    """One table owns every font, the way one already owns the colours."""

    def test_no_module_but_theme_sizes_a_font_by_a_LITERAL(self):
        """Point-size literals only; pixel sizes are ▸p/designed-dialog."""
        offenders = []
        for folder, _dirs, names in os.walk(PACKAGE):
            if os.path.basename(folder) in ("tests", "__pycache__"):
                continue
            for name in sorted(names):
                if not name.endswith(".py") or name == "theme.py":
                    continue
                relative = os.path.relpath(os.path.join(folder, name), PACKAGE)
                tree = ast.parse(source_of(relative))
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    attr = getattr(node.func, "attr", "")
                    if attr not in ("setPointSize", "setPointSizeF"):
                        continue
                    for arg in node.args:
                        if any(isinstance(n, ast.Constant)
                               and isinstance(n.value, (int, float))
                               for n in ast.walk(arg)):
                            offenders.append("%s:%d" % (relative, node.lineno))
        self.assertEqual(
            [], offenders,
            "a font size is written as a number outside theme.py (%s) - "
            "that is the shape that gave the panel four independent font "
            "rules, each right only where it was written"
            % ", ".join(offenders))

    def test_the_floor_follows_the_UI_SCALE(self):
        """The floor is `ui_px(12)`, which at scale 1.0 looks like a raw 12."""
        source = func_source("helpers/theme.py", "ui_font")
        self.assertIn(
            "ui_px(MIN_UI_POINTS)", source,
            "the floor is back to an unscaled constant, so the panel "
            "ignores Global UI Size where the host honours it")

    def test_a_role_derives_and_never_decides(self):
        from amaze.helpers import theme as theme_mod
        base = QtGui.QFont()
        base.setPointSizeF(20.0)          # above the floor, so it stands
        title = theme_mod.font("empty_headline", base)
        self.assertAlmostEqual(25.0, title.pointSizeF(), places=3,
                               msg="the empty headline stopped deriving "
                                   "from the font it relates to")
        self.assertTrue(title.bold())
        self.assertAlmostEqual(
            20.0, base.pointSizeF(), places=3,
            msg="it mutated the caller's font instead of copying it")

    def test_an_unknown_role_raises_rather_than_guessing(self):
        from amaze.helpers import theme as theme_mod
        with self.assertRaises(KeyError):
            theme_mod.font("subtilte")

    def test_the_floor_leaves_a_PIXEL_sized_font_alone(self):
        """A pixel-sized font answers -1 to `pointSizeF`; clamping converts it."""
        from amaze.helpers import theme as theme_mod
        pixel = QtGui.QFont()
        pixel.setPixelSize(9)
        self.assertEqual(-1, pixel.pointSize())
        self.assertEqual(9, theme_mod.ui_font(pixel).pixelSize(),
                         "a pixel-sized font was converted to points")

    def test_a_ROLE_leaves_a_pixel_sized_font_alone_as_well(self):
        """The floor's `> 0` gate has to hold on the SCALE too: -1 times any role factor is still a size Qt refuses, so the role hands it one and Qt drops it with a warning per call."""
        from amaze.helpers import theme as theme_mod
        pixel = QtGui.QFont()
        pixel.setPixelSize(9)
        refused = []
        QtCore.qInstallMessageHandler(
            lambda mode, ctx, message: refused.append(message))
        self.addCleanup(QtCore.qInstallMessageHandler, None)
        title = theme_mod.font("comments_title", pixel)
        QtCore.qInstallMessageHandler(None)
        self.assertEqual(
            [], [line for line in refused if "setPointSizeF" in line],
            "the role scaled -1 and handed Qt a size it refuses")
        self.assertEqual(9, title.pixelSize(),
                         "a pixel-sized font was converted to points")
        self.assertTrue(title.bold(), "the role lost its weight")


class PaintingTheSidebarNeverTouchesTheDisk(unittest.TestCase):

    def test_a_paint_only_asks_for_a_count(self):
        """The walk runs on the count worker; `data()` and what it calls on a miss only ask."""
        for name in ("data", "_folder_count", "_ask_count"):
            source = func_source("core/folders.py", name)
            for walk in ("listdir", "walk_following_links", "count_files("):
                self.assertNotIn(
                    walk, source,
                    "%s reaches %s on the GUI thread - for a recursive "
                    "location a full walk with a realpath per directory "
                    "and per child, inside paint" % (name, walk))

    def test_a_row_still_counts_its_own_folder(self):
        source = func_source("core/folders.py", "data")
        self.assertIn(
            "self._folder_count(path)", source,
            "the per-row count is gone - the sidebar would show no "
            "numbers at all")


class EveryActivateEstablishesADefaultRow(unittest.TestCase):

    def test_all_four_use_the_shared_helper(self):
        """`setModel` leaves nothing selected, and one `activate` fixes it."""
        self.assertIn(
            "self._stand_on_first_row()",
            method_source("panel/sections.py", "AssetSection",
                          "activate"),
            "AssetSection.activate establishes its default sidebar "
            "row on its own again, or not at all")
        self.assertIn(
            "_select_default_sidebar_row",
            method_source("panel/sections.py", "AssetSection",
                          "_stand_on_first_row"),
            "the shared default row no longer goes through the panel's helper")
        from amaze.panel import sections
        self.assertIs(
            sections.GradientSection.activate,
            sections.AssetSection.activate,
            "Color carries its own activate again - if that is "
            "deliberate, scan its body here like the shared one")


class TheGridPaneIsResolvedByElimination(_PanelCase):
    """Both side panes hold their width; the grid is the one that flexes."""

    def test_thumblist_is_not_a_pane_but_a_child_of_one(self):
        """`thumblist` sits inside the grid pane, so `indexOf` gives -1."""
        splitter = None
        for child in self.panel.ui.findChildren(QtWidgets.QSplitter):
            if child.indexOf(self.panel.cat_wrapper) != -1:
                splitter = child
                break
        self.assertIsNotNone(splitter, "no splitter holds the sidebar")
        self.assertEqual(
            -1, splitter.indexOf(self.panel.thumblist),
            "thumblist is a splitter pane now - the construction "
            "changed under everything written on top of it")


class AnOnlineBatchSurvivesOneBadRecord(unittest.TestCase):

    def test_both_import_loops_guard_each_record(self):
        """`import_record` has only try/finally, so a raise aborts the loop."""
        for name in ("_import_online_records",
                     "_import_online_records_to_scene"):
            self.assertIn(
                "except Exception", func_source("panel/panel.py", name),
                "%s abandons its batch on a raising record" % name)


class TheCommentGlyphsAreRasterisedOnce(unittest.TestCase):

    def test_the_glyph_cache_keys_on_every_input(self):
        """This runs inside a block walk that repaints twice a second."""
        from amaze.panel import notes_panel

        notes_panel._glyph_cache.clear()
        first = notes_panel._feather_icon("check", 14, "#5cc9f5")
        again = notes_panel._feather_icon("check", 14, "#5cc9f5")
        self.assertIs(
            first, again,
            "the glyph is re-rasterised on every call - a file open and "
            "an SVG parse per to-do per repaint")
        notes_panel._feather_icon("check", 14, "#ffffff")
        self.assertGreaterEqual(
            len(notes_panel._glyph_cache), 2,
            "the ink is not in the cache key, so a checked and an "
            "unchecked to-do would share one pixmap")


class TheColourBandFollowsTheOwningLocation(unittest.TestCase):
    """The owning location resolves by prefix, once per folder, cached."""

    def test_a_subfolder_row_wears_the_locations_colour(self):
        from unittest import mock

        from amaze.core import locations

        prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        root = tempfile.mkdtemp(prefix="amaze_colour_root_")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        sub = os.path.join(root, "deeper")
        os.makedirs(sub)
        locations.register(prefs, root)
        prefs.set_file_folder_color(root, "#123456")

        model = file_library.FileFiles(prefs)
        self.assertEqual(
            "#123456", model._folder_colour(sub),
            "a subfolder row of a recursive location paints bandless")
        self.assertEqual("#123456", model._folder_colour(root))

        calls = []
        real_record = locations.record

        def counting(preferences, path):
            calls.append(str(path))
            return real_record(preferences, path)

        with mock.patch.object(locations, "record", counting):
            model._folder_colour(sub)
            model._folder_colour(sub)
        self.assertEqual(
            [], calls,
            "the paint path re-reads a record per tile - the folder "
            "cache is not holding")

        model.colours_changed()
        with mock.patch.object(locations, "record", counting):
            model._folder_colour(sub)
        self.assertTrue(calls, "colours_changed did not drop the cache")


class AnUnconfiguredPanelStillOpensPreferences(unittest.TestCase):
    """Preferences is the only way to configure a library, so it must open."""

    def test_show_prefs_survives_no_library(self):
        self.addCleanup(test_support.reset_database_singletons)
        panel = test_support.fixture_unconfigured_panel(self)
        self.assertIsNone(
            getattr(panel, "material_model", "missing"),
            "premise: the panel took the no-library branch")
        self.assertIsNone(
            getattr(panel, "file_files_model", "missing"),
            "the File models were left unset - any reader raises "
            "AttributeError instead of seeing None")
        panel.show_prefs()          # raised before the fix
        dialog = getattr(panel, "_prefs_dialog", None)
        self.assertIsNotNone(dialog, "no dialog was built")
        dialog.close()


class TheOnlineWorldNeedsALibrary(unittest.TestCase):
    """The online model is built by setup(), which a panel with no library never runs."""

    def setUp(self):
        self.addCleanup(test_support.reset_database_singletons)
        self.panel = test_support.fixture_unconfigured_panel(self)
        self.assertIsNone(getattr(self.panel, "material_model", "missing"),
                          "premise: the panel took the no-library branch")

    def _assert_still_local(self):
        self.assertFalse(self.panel._is_online(),
                         "the panel is left half in the online world")
        self.assertFalse(self.panel.btn_online.isChecked(),
                         "the Online chip reads on with nothing behind it")

    def test_the_door_refuses_and_says_so_on_the_chip(self):
        self.panel.enter_online_world()
        self._assert_still_local()

    def test_the_chip_raises_nothing_and_stays_off(self):
        from unittest import mock

        raised = []
        with mock.patch.object(sys, "excepthook",
                               lambda *info: raised.append(info[1])):
            self.panel.btn_online.click()
            self.panel.btn_online.setChecked(True)    # past a disabled chip
        self.assertEqual([], raised, "the Online chip raised in its slot")
        self._assert_still_local()
        self.assertFalse(self.panel.btn_online.isEnabled(),
                         "the Online chip is live on a panel with no "
                         "library")

    def test_every_route_in_goes_through_the_door(self):
        self.panel.open_online_source("PhysicallyBased")
        self._assert_still_local()


class EveryGridProxyIsSetUpOneWay(_PanelCase):
    """Six grid proxies, one set-up: the base class does the re-sort Qt's dynamic mode would."""

    def test_no_grid_proxy_sorts_or_filters_dynamically(self):
        names = ("material_sorted_model", "cop_sorted_model", "code_sorted_model",
                 "file_sorted_model", "gradient_sorted_model", "matx_sorted_model")
        dynamic = [name for name in names
                   if getattr(self.panel, name).dynamicSortFilter()]
        self.assertEqual([], dynamic)

    def test_file_still_drops_an_unstarred_row_once_the_loop_turns(self):
        """With Qt's dynamic mode off, the base class's pass is what re-filters File."""
        panel = self.panel
        panel.section_tabs.setChecked("file")
        QtWidgets.QApplication.processEvents()
        self.addCleanup(panel.section_tabs.setChecked, "material")
        self.addCleanup(panel.cb_favsonly.setChecked, False)
        proxy, files = panel.file_sorted_model, panel.file_files_model
        self.assertTrue(proxy.rowCount(), "premise: File shows files")
        row = proxy.mapToSource(proxy.index(0, 0)).row()
        files.toggle_favorite(row)
        panel.cb_favsonly.setChecked(True)
        QtWidgets.QApplication.processEvents()
        self.assertEqual(1, proxy.rowCount(), "premise: one starred file shows")
        files.toggle_favorite(row)
        QtWidgets.QApplication.processEvents()
        self.assertEqual(0, proxy.rowCount(), "the unstarred file stayed")

    def test_every_grid_proxy_has_its_own_selection(self):
        pairs = (("material_sorted_model", "material_selection_model"),
                 ("cop_sorted_model", "cop_selection_model"),
                 ("code_sorted_model", "code_selection_model"),
                 ("file_sorted_model", "file_selection_model"),
                 ("gradient_sorted_model", "gradient_selection_model"),
                 ("matx_sorted_model", "matx_selection_model"))
        for proxy, selection in pairs:
            with self.subTest(proxy):
                self.assertIs(getattr(self.panel, proxy),
                              getattr(self.panel, selection).model())


class AStartOnAnySectionTakesTheOnePath(unittest.TestCase):
    """The section a panel opens on is shown the way a tab click shows it, once."""

    def test_a_start_off_material_syncs_and_fills_the_menu_once(self):
        from unittest import mock
        from amaze.panel import panel as panel_mod

        calls = []
        real_menu = panel_mod.AmazePanel.build_filter_menu
        real_sync = panel_mod.AmazePanel._sync_toolbar

        def menu(panel):
            calls.append("filter menu")
            return real_menu(panel)

        def sync(panel, context):
            calls.append("toolbar")
            return real_sync(panel, context)

        shown = ("gradient", "cop", "code", "file")
        with mock.patch.object(test_support, "ALL_SECTION_KEYS", shown), \
                mock.patch.object(panel_mod.AmazePanel, "build_filter_menu", menu), \
                mock.patch.object(panel_mod.AmazePanel, "_sync_toolbar", sync):
            panel = test_support.fixture_panel(self)
        self.assertEqual("gradient", panel.current_section, "premise: Colors opens")
        self.assertEqual((1, 1), (calls.count("toolbar"), calls.count("filter menu")),
                         calls)


class TheOnlineChipIsLiveOnceALibraryIsOpen(_PanelCase):

    def test_setup_turns_the_chip_on(self):
        self.assertTrue(self.panel.btn_online.isEnabled(),
                        "a panel with a library opened with Online off")


class LeavingOnlineLandsOnAShownSection(unittest.TestCase):
    """Online entered from Node, Node hidden in Preferences, then Online left."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)

    def _close_preferences_hiding(self, key):
        settings = os.path.join(self.panel.prefs.path, "settings.json")
        with open(settings, encoding="utf-8") as handle:
            data = json.load(handle)
        data["enabled_sections"] = [k for k in data["enabled_sections"]
                                    if k != key]
        with open(settings, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        self.panel._prefs_dialog_closed(self.panel.prefs.dir)
        QtWidgets.QApplication.processEvents()

    def test_the_grid_shows_the_section_of_the_tab_it_lands_on(self):
        panel = self.panel
        panel.section_tabs.setChecked("cop")
        QtWidgets.QApplication.processEvents()
        self.assertEqual("cop", panel.current_section, "premise: on Node")
        panel.enter_online_world()
        self.assertTrue(panel._is_online(), "premise: online")

        self._close_preferences_hiding("cop")
        panel.leave_online_world()
        QtWidgets.QApplication.processEvents()

        landed = panel.section_tabs._checked_key
        self.assertIn(landed, panel.prefs.enabled_sections,
                      "leaving Online landed on a hidden tab")
        self.assertEqual(landed, panel.current_section,
                         "the tab shown and the section behind it disagree")
        self.assertIs(
            panel.sections[landed].stack().proxy, panel.thumblist.model(),
            "the %s tab shows another section's tiles" % landed)


class ClosingPreferencesRescansTheFileFolderOnce(unittest.TestCase):
    """Closing Preferences over File rescans its folder once, and not at all while Online shows."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.panel.section_tabs.setChecked("file")
        QtWidgets.QApplication.processEvents()
        self.files = self.panel.file_files_model

    def _scans_while(self, action):
        from unittest import mock
        with mock.patch.object(self.files, "_scan",
                               wraps=self.files._scan) as scan:
            action()
            QtWidgets.QApplication.processEvents()
        return scan.call_count

    def _close_preferences(self):
        self.panel._prefs_dialog_closed(self.panel.prefs.dir)

    def test_the_folder_showing_is_scanned_once(self):
        one_pass = self._scans_while(self.files.refresh_current_folder)
        self.assertGreater(one_pass, 0, "premise: File shows a folder")
        self.assertEqual(one_pass, self._scans_while(self._close_preferences),
                         "closing Preferences scanned the folder more than once")

    def test_closing_onto_another_library_scans_its_location_once(self):
        old = self.panel.prefs.dir
        theirs = test_support.fresh_files_folder(self)
        settings = os.path.join(self.panel.prefs.path, "settings.json")
        with open(settings, encoding="utf-8") as handle:
            data = json.load(handle)
        data.update(directory=test_support.fresh_library(self),
                    file_folders=[theirs], last_file_folder=theirs,
                    file_location_records={theirs: {"registered": True}})
        with open(settings, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        scans = self._scans_while(lambda: self.panel._prefs_dialog_closed(old))
        self.assertEqual(theirs, self.files._folder, "premise: File shows the new location")
        self.assertEqual(1, scans, "the new library's location was scanned %d times" % scans)

    def test_nothing_is_scanned_while_online_shows(self):
        self.panel.enter_online_world()
        self.addCleanup(self.panel.leave_online_world)
        self.assertTrue(self.panel._is_online(), "premise: online")
        self.assertEqual(0, self._scans_while(self._close_preferences),
                         "closing Preferences scanned a File folder nobody sees")


class TheGridCannotBeSqueezedOutOfExistence(unittest.TestCase):
    """Three floors: the grid pays for both side panes, so the panel's proves nothing."""

    def setUp(self):
        from amaze.tests import test_support

        self.panel = test_support.fixture_panel(self)

    def _splitter(self):
        """By search: a `HeldPane` makes the splitter a grandparent."""
        from PySide6 import QtWidgets

        found = self.panel.findChildren(QtWidgets.QSplitter)
        return found[0] if found else None

    def test_the_window_carries_the_only_width_floor(self):
        """ONE number, on the window, and nothing else."""
        from amaze.helpers import theme
        from amaze.panel import panel as panel_mod

        self.assertEqual(theme.ui_px(panel_mod.MIN_PANEL_WIDTH),
                         self.panel.ui.minimumWidth())

    def test_no_pane_holds_a_minimum_of_its_own(self):
        """A child minimum propagates up and moves the window as Comments opens."""
        splitter = self._splitter()
        self.assertIsNotNone(splitter, "premise: the three panes are a "
                                       "splitter")
        grid_pane = splitter.widget(1)
        self.assertEqual(0, grid_pane.minimumWidth(),
                         "a minimum here adds itself to the window's own, "
                         "so the window stops honouring its 500")


class ABlockCommentSurvivesTheLineBreak(unittest.TestCase):
    """`spans()` sees ONE line, so a `/* */` crossing lines used to leave every line after the opener highlighted as code. ▸p/vex-block-comments"""

    def _painted(self, lines):
        """Run the highlighter over `lines`, returning [(text, [(start, length, colour)])] and the block state each line ends in."""
        from amaze.helpers import vex_syntax

        painted = []

        class _Recorder(vex_syntax.VexHighlighter):
            def __init__(self):
                self.state = -1
                self.runs = []

            def previousBlockState(self):
                return self.state

            def setCurrentBlockState(self, value):
                self.state = value

            def setFormat(self, start, length, fmt):
                self.runs.append(
                    (start, length, fmt.foreground().color().name()))

        recorder = _Recorder()
        for line in lines:
            recorder.runs = []
            recorder.highlightBlock(line)
            painted.append((line, list(recorder.runs), recorder.state))
        return painted

    def _all_comment(self, runs, text):
        from amaze.helpers import vex_syntax
        covered = set()
        for start, length, colour in runs:
            if colour == vex_syntax.COMMENT.name():
                covered.update(range(start, start + length))
        return covered >= set(range(len(text)))

    def test_the_lines_inside_a_block_comment_are_all_comment(self):
        rows = self._painted([
            "int a = 1;   /* opens here",
            "still inside the comment",
            "and closes */ int b = 2;",
        ])
        self.assertTrue(
            self._all_comment(rows[1][1], rows[1][0]),
            "a line wholly inside /* */ was highlighted as code")
        from amaze.helpers import vex_syntax
        opener_tail = [run for run in rows[0][1] if run[0] >= 13]
        self.assertTrue(opener_tail, "nothing was painted after the /*")
        self.assertTrue(
            all(colour == vex_syntax.COMMENT.name()
                for _start, _length, colour in opener_tail),
            "the text after /* on the opening line is not comment-coloured")

    def test_the_state_carries_and_then_clears(self):
        rows = self._painted([
            "/* open",
            "inside",
            "close */ int b;",
            "int c;",
        ])
        self.assertEqual(1, rows[0][2], "the opener did not set the state")
        self.assertEqual(1, rows[1][2], "the state did not carry")
        self.assertEqual(0, rows[2][2], "the closer did not clear the state")
        self.assertEqual(0, rows[3][2], "a later line is still in comment")

    def test_a_slash_star_inside_a_string_opens_nothing(self):
        from amaze.helpers import vex_syntax
        self.assertIsNone(
            vex_syntax.open_comment_at('string s = "not /* a comment";'),
            "a /* inside a string opened a block comment")
        self.assertIsNone(
            vex_syntax.open_comment_at("// /* after a line comment"),
            "a /* after // opened a block comment")

    def test_a_comment_closed_on_its_own_line_opens_nothing(self):
        from amaze.helpers import vex_syntax
        self.assertIsNone(
            vex_syntax.open_comment_at("/* closed on one line */ int b;"))
        self.assertEqual(
            14, vex_syntax.open_comment_at("a /* one */ b /* two"),
            "a second, unterminated /* on the same line was missed")


class TheHighlighterReadsEachLineOnce(unittest.TestCase):
    """One tokenizer pass per line, painting the colours the two-pass highlighter painted."""

    PAINTED = [    # (line, one letter per character, block state) as painted before the change
        ("int a = 1;   /* opens here",
         "tttdddddnddddccccccccccccc", 1),
        ("still inside the comment",
         "cccccccccccccccccccccccc", 1),
        ("and closes */ vector v = set(1, 2.5, 3); foo (x);",
         "cccccccccccccdttttttdddddfffdnddnnnddndddfffddddd", 0),
        ('string s = "not /* a comment"; f@pscale = fit01 (rand(@ptnum), 0.1);',
         "ttttttdddddssssssssssssssssssddaaaaaaaadddfffffddffffdaaaaaadddnnndd", 0),
        ("bar /* (open after a word",
         "ddddccccccccccccccccccccc", 1),
        ("*/ return addpoint(0, @P) // tail /* ignored",
         "ccdkkkkkkdffffffffdnddaaddcccccccccccccccccc", 0),
        ("a /* one */ b /* two",
         "ddcccccccccdddcccccc", 1),
        ("*/", "cc", 0),
        ("#include <math.h>", "ccccccccccccccccc", 0),
        ("if (x) { i@id = 'c'; } else { break; }",
         "kkdddddddaaaadddsssddddkkkkdddkkkkkddd", 0),
    ]

    def _letters(self, line, runs):
        from amaze.helpers import vex_syntax as vs
        names = {vs.DEFAULT.name(): "d", vs.COMMENT.name(): "c",
                 vs.STRING.name(): "s", vs.NUMBER.name(): "n",
                 vs.TYPE.name(): "t", vs.KEYWORD.name(): "k",
                 vs.FUNCTION.name(): "f", vs.ATTRIB.name(): "a"}
        chars = ["."] * len(line)
        for start, length, colour in runs:
            for i in range(start, start + length):
                chars[i] = names[colour]
        return "".join(chars)

    def test_the_colours_are_the_ones_painted_before(self):
        rows = ABlockCommentSurvivesTheLineBreak._painted(
            self, [line for line, _letters, _state in self.PAINTED])
        for (line, letters, state), (_text, runs, got_state) in zip(
                self.PAINTED, rows):
            with self.subTest(line=line):
                self.assertEqual(letters, self._letters(line, runs))
                self.assertEqual(state, got_state)

    def test_a_line_that_opens_a_comment_is_tokenized_once(self):
        from unittest import mock
        from amaze.helpers import vex_syntax
        real = vex_syntax._TOKEN_RE
        passes = []

        class Counting:
            def finditer(self, *args, **kwargs):
                passes.append(args[0] if args else "")
                return real.finditer(*args, **kwargs)

            def __getattr__(self, name):
                return getattr(real, name)

        with mock.patch.object(vex_syntax, "_TOKEN_RE", Counting()):
            ABlockCommentSurvivesTheLineBreak._painted(
                self, ["int a = 1;   /* opens here", "still inside",
                       "closes */ foo(1);"])
        self.assertEqual(
            2, len(passes),
            "the highlighter tokenized a line more than once: %r" % passes)


class TheHighlighterBuildsOneFormatPerColour(unittest.TestCase):
    """A re-highlight paints thousands of runs, so each colour's format is built once and shared."""

    def _handed(self):
        """Every format the highlighter hands Qt over the golden lines."""
        from amaze.helpers import vex_syntax
        handed = []

        class _Recorder(vex_syntax.VexHighlighter):
            def __init__(self):
                self.state = -1

            def previousBlockState(self):
                return self.state

            def setCurrentBlockState(self, value):
                self.state = value

            def setFormat(self, start, length, fmt):
                handed.append(fmt)

        recorder = _Recorder()
        for line, _letters, _state in TheHighlighterReadsEachLineOnce.PAINTED:
            recorder.highlightBlock(line)
        return handed

    def test_each_colour_is_painted_with_one_format(self):
        handed = self._handed()
        colours = {fmt.foreground().color().rgba() for fmt in handed}
        self.assertEqual(
            len(colours), len({id(fmt) for fmt in handed}),
            "%d runs in %d colours were painted with a new format each"
            % (len(handed), len(colours)))

    def test_a_shared_format_carries_only_its_colour(self):
        for fmt in self._handed():
            fresh = QtGui.QTextCharFormat()
            fresh.setForeground(fmt.foreground().color())
            self.assertEqual(fresh, fmt,
                             "a shared format carries more than its colour")


if __name__ == "__main__":
    unittest.main()
