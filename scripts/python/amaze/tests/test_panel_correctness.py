"""Panel and UI correctness: one route per question, not three."""

import ast
import os
import re
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

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
            self._calls("panel/panel.py", "MatLibPanel",
                        "_prefs_dialog_closed", "sidebar_proxies"),
            "the Preferences push enumerates the proxies by hand "
            "again - the enumeration that was short is exactly how "
            "Code was missed")

    def test_sidebar_proxies_names_all_four(self):
        from amaze.panel import panel as panel_mod
        self.assertEqual(
            {"material", "cop", "code", "gradient"},
            set(panel_mod.MatLibPanel.SIDEBAR_PROXY_ATTRS),
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
        for name in ("_current_code_category", "save_cop_from_node",
                     "get_material_info_user"):
            self.assertIn(
                "_selected_category_name", func_source("panel/panel.py", name),
                "%s answers 'which category is selected' on its own "
                "again" % name)


class CaptureIsDecidedInOnePlace(unittest.TestCase):

    def test_the_tile_menu_does_not_re_decide(self):
        """The policy is only that the target is the current scene."""
        source = func_source("panel/sections.py", "menu_capture_enabled")
        self.assertNotIn(
            "amaze_opened_current_scene", source,
            "the tile's Capture gate re-decides the retired rule; the "
            "shared path dropped it deliberately and the shelf tool "
            "cannot be made to share it")
        self.assertIn(
            "current_scene_path", source,
            "the gate no longer tests the thing the capture is filed "
            "against")

    def test_the_shared_policy_still_does_not_require_it(self):
        self.assertNotIn(
            "amaze_opened_current_scene",
            func_source("core/scene_captures.py", "capture_open_scene"),
            "the shared policy grew the retired clause back")


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

    def test_both_hand_painted_toolbar_widgets_use_the_shared_rule(self):
        source = source_of("helpers/ui_helpers.py")
        tree = ast.parse(source)
        applies = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if node.name not in ("ChipToggleButton", "IconMenuButton",
                                 "ClickSlider"):
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.FunctionDef) and \
                        child.name == "paintEvent":
                    applies[node.name] = "apply_disabled_opacity" in \
                        ast.dump(child)
        self.assertEqual(
            {"ChipToggleButton": True, "IconMenuButton": True,
             "ClickSlider": True}, applies,
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
        self.assertEqual("asset_delegate", sections.CodeSection.delegate_attr,
                         "Code points the grid at the Materials delegate")
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
                    and target.attr in ("thumb_delegate", "asset_delegate")):
                continue
            version_roles[target.attr] = any(
                kw.arg in ("versions_role", "active_version_role")
                for kw in getattr(node.value, "keywords", []))
        self.assertEqual(
            {"thumb_delegate": True, "asset_delegate": False}, version_roles,
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
            panel_mod.MatLibPanel.COLUMN_DEFAULT_WIDTH)
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
        source = func_source("panel/panel.py", "_on_folder_progress")
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
        title = theme_mod.font("comments_title", base)
        self.assertAlmostEqual(28.0, title.pointSizeF(), places=3,
                               msg="the comments title stopped deriving "
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


class PaintingTheSidebarNeverTouchesTheDisk(unittest.TestCase):

    def test_the_all_row_only_sums_what_is_already_counted(self):
        """`_counts` keeps painting off the disk, and `activate` empties it."""
        source = func_source("core/folders.py", "data")
        all_branch = source[source.index('if row == 0:', 0):]
        all_branch = all_branch[:all_branch.index("path = self._folders()")]
        self.assertNotIn(
            "self._folder_count(", all_branch,
            "the All row forces a count for every registered location "
            "inside data(), which for a recursive one is a full "
            "walk_following_links with a realpath per directory AND per "
            "child name - synchronously, inside paint")

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
            "_select_default_sidebar_row",
            method_source("panel/sections.py", "AssetSection",
                          "activate"),
            "AssetSection.activate establishes its default sidebar "
            "row on its own again, or not at all")
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


class TheAccentReachesEveryDelegateAtBirth(_PanelCase):
    """`tile_delegates` derives from the sections, so the sweep runs after."""

    def test_every_tile_delegate_wears_the_accent(self):
        """Vacuous under a default accent; the order test below is the pin."""
        panel = self.panel
        delegates = panel.tile_delegates()
        self.assertGreaterEqual(
            len(delegates), 4,
            "premise: the delegates exist and are enumerable")
        expected = theme.accent(panel.prefs.accent_color)
        wrong = [type(d).__name__ for d in delegates
                 if d.DIM != expected]
        self.assertEqual([], wrong)

    def test_the_sweep_runs_after_the_sections_exist(self):
        """Read as order: a painted result cannot tell a dead sweep from a live one."""
        import inspect
        import textwrap

        from amaze.panel import panel as panel_mod

        source = textwrap.dedent(
            inspect.getsource(panel_mod.MatLibPanel.setup))
        tree = ast.parse(source)
        sections_line = sweep_line = None
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and getattr(node.func, "attr", "")
                    == "build_sections"):
                sections_line = node.lineno
            if (isinstance(node, ast.For)
                    and isinstance(node.iter, ast.Call)
                    and getattr(node.iter.func, "attr", "")
                    == "tile_delegates"):
                sweep_line = node.lineno
        self.assertIsNotNone(sections_line, "build_sections not found")
        self.assertIsNotNone(sweep_line, "the accent sweep not found")
        self.assertGreater(
            sweep_line, sections_line,
            "the accent sweep runs before the sections exist, so "
            "tile_delegates() is empty and every subtitle keeps the "
            "class default until Preferences is opened once")


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


if __name__ == "__main__":
    unittest.main()
