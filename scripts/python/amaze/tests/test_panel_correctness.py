"""Panel and UI correctness: one route per question, not three.

BATCH 3's shape. Nothing here loses data and nothing here is slow by
accident; what these findings share is a question answered in several
places that had drifted apart, or a rule stated in a doc that the code
did not deliver:

  * the sidebar filter reached only the Materials category model, so a
    Node category could show "5" and open EMPTY - which
    CategoriesSidebarProxy's own docstring says cannot happen;
  * the File tile's Capture gate was the third copy of a policy the
    other two had already dropped a clause from;
  * three sites acted on a category by its DISPLAYED name, which
    strips a leading underscore, so Rename did nothing, Remove left
    the row, and a drop created a second category;
  * two self-painted widgets never dimmed when disabled, though
    overview.md states both do;
  * Node and Code borrowed the Materials delegate and got its Version
    column - and its versions dialog, which maps through the MATERIAL
    model.

Several of these read the SOURCE, deliberately: a behaviour test
cannot see that one of four enumerations of the same three models is
short, and that is precisely how three of them shipped.
"""

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
    """A Prefs holding only what a location record is composed from.

    A real Prefs built under hython resolves $AMAZE to the live install,
    which is how a test overwrote real settings once - so this borrows
    the class's own accessors without its constructor.
    """
    prefs = prefs_mod.Prefs.__new__(prefs_mod.Prefs)
    prefs.save = lambda: None
    prefs._directory = tempfile.mkdtemp(prefix="amaze_locations_")
    # THE COPY IS THE SEED, and `data` says the library has not taken
    # over yet - which is what makes the four settings surfaces below
    # the answer until the first read migrates them into the store. The
    # four dicts these tests used to poke are derived now, so setting
    # them would have been accepted and ignored.
    prefs.data = {}
    prefs._file_folders = []
    prefs._file_favorites = []
    prefs._file_folder_names = dict(names)
    prefs._file_folder_colors = dict(colors)
    prefs._file_folder_show_all = dict(show_all)
    prefs._file_recursive_folders = list(recursive)
    for path in set(names) | set(colors) | set(show_all) | set(recursive):
        prefs._file_folders.append(path)
    prefs._load_location_copy({})
    # AND TAKE IT INTO THE LIBRARY, which is what load() does on a real
    # Prefs. Without it the store is empty, so `retire_prefix` and
    # `relocate` sweep nothing and pass while doing nothing at all.
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
    """One METHOD's source, scoped to its class.

    func_source below walks the whole module and returns the first
    match - which for `apply_filter` is the base Section's no-op stub,
    not AssetSection's real one. Scoping matters wherever a name is
    overridden, which in this package is most of them.
    """
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
    """One function's source, by AST rather than by slicing on
    "\\n    def " - which breaks on the last function in a file and on
    nesting, and produced two wrong readings while this batch was
    being written."""
    text = source_of(relative)
    tree = ast.parse(text)
    lines = text.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == name:
            return "\n".join(lines[node.lineno - 1:node.end_lineno])
    raise AssertionError("no function %r in %s" % (name, relative))


class _PanelCase(unittest.TestCase):
    """A REAL panel on a fixture library. fixture_panel is the only way
    one is built here - it asserts every path it would touch is inside
    the tempdir before it returns."""

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
        """MaterialSection overrode apply_filter to also push the
        choice into its category model - and that push is what makes
        the sidebar list only categories holding a visible asset. Node
        and Code inherited the grid half alone, so nothing ever called
        set_renderer_filter on their category models: every row was
        accepted and every asset counted regardless of context or
        language."""
        from amaze.panel import sections
        for name in ("CopSection", "CodeSection", "MaterialSection"):
            cls = getattr(sections, name)
            self.assertNotIn(
                "apply_filter", cls.__dict__,
                "%s overrides apply_filter again - the sidebar push "
                "belongs to the shared route, or two of the three "
                "sections silently do not get it" % name)

    def test_the_shared_route_pushes_into_the_sections_own_model(self):
        """By AST: the DOCSTRING of apply_filter explains the push by
        name, so a text search matched it and the test stayed green
        with the call deleted. Sabotage caught that, and it is the same
        shape as the batch-2 test that matched its own comment - when a
        test greps source, it must grep for a STRUCTURE."""
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
        """Hide Empty Categories was pushed into two of the three
        proxies; Code kept its construction-time value for the run."""
        # By AST, for the same reason as above: the comment beside the
        # loop names sidebar_proxies(), so a text search passed with
        # the call removed.
        self.assertTrue(
            self._calls("panel/panel.py", "MatLibPanel",
                        "_prefs_dialog_closed", "sidebar_proxies"),
            "the Preferences push enumerates the proxies by hand "
            "again - the enumeration that was short is exactly how "
            "Code was missed")

    def test_sidebar_proxies_names_all_three(self):
        from amaze.panel import panel as panel_mod
        self.assertEqual(
            {"material", "cop", "code"},
            set(panel_mod.MatLibPanel.SIDEBAR_PROXY_ATTRS),
            "an asset section gained or lost a sidebar without the "
            "one list that every push walks")


class ACategoryIsActedOnByItsStoredName(_PanelCase):
    """`Categories.data` returns elem[1:] for DisplayRole when the
    stored name starts with "_" - the mechanism that makes "_All" sort
    first and read as "All"."""

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
        """The two sites still in the panel read the helper directly.

        The sidebar MENU was a third (`_asset_catlist_menu`) until
        batch 7 moved it onto the section 2026-08-04; its rename and
        remove verbs read `sidebar_key`, and `AssetSection.sidebar_key`
        is the helper. Checked as that chain rather than dropped,
        because the guarantee is the same one - a category acts on the
        name it STORES."""
        # The drop-target sites moved to panel/sidebar.py with the
        # drag-hover cluster (batch 7, 2026-08-04); the panel keeps
        # one-line delegations. The guarantee is unchanged, so the test
        # follows the code rather than being relaxed.
        for name in ("droppable_index", "category_at_point"):
            source = func_source("panel/sidebar.py", name)
            self.assertIn(
                "_raw_category_name", source,
                "%s reads a category name without the helper - a "
                "fourth site getting this wrong is what the helper "
                "exists to stop" % name)

        # method_source, not func_source: the latter walks the module
        # and returns the FIRST match, which is the base Section's
        # stub. This file's own docstring says why that helper exists.
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
        """Three copies served the save dialogs and already disagreed:
        only one fell back to live_current_index, which is the state
        _restore_section_state reaches through setCurrentIndex without
        a select - so the Node dialog defaulted to Uncategorized where
        the Materials one pre-selected the category."""
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
        """The shared policy requires only that the target IS the
        current scene. The tile menu was the third copy and the only
        one that kept the retired extra clause that AMAZE had opened
        it - so a scene opened through File > Open, a recent-files
        entry or a crash recovery was capturable from the toolbar and
        greyed out on its own tile."""
        # The gate is `FolderSection.menu_capture_enabled` since the
        # seven menus became one table (batch 6); it was
        # `panel._file_rc_menu` when this test was written.
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
    """overview.md is the system map, and a map that silently stops
    covering the territory is worse than none - it is consulted and
    believed. Nine modules had accumulated in it unnamed."""

    #: Documented as a PHRASE rather than a path - the map's
    #: `helpers/  theme, ui widgets, vex syntax, generic helpers` line.
    #: Named here so the shorthand is a DECISION rather than a hole
    #: this test cannot see. Brace forms are NOT here: they are
    #: expanded below, because they name their directory and are
    #: therefore checkable.
    SHORTHAND = {"helpers/theme.py", "helpers/helpers.py",
                 "helpers/vex_syntax.py"}

    @staticmethod
    def _brace_paths(body):
        """Expand `core/{texture,geo}_library.py` into real paths.

        The map compresses siblings this way deliberately. A checker
        that cannot read the compression would force the map to spell
        every one out, which is a worse map."""
        paths = set()
        for match in re.finditer(r"([\w/]+)/\{([^}]*)\}([\w.]*)", body):
            head, alternatives, tail = match.groups()
            for alternative in alternatives.split(","):
                paths.add("%s/%s%s" % (head, alternative.strip(), tail))
        return paths

    def test_the_map_places_every_module_in_its_directory(self):
        """The map must name the module WITH its directory.

        It used to look for the bare stem anywhere in the document, and
        that is two different holes. A module could move between
        directories and the map went on naming the old path with
        nothing red - which is exactly what a package move does. And
        the check was satisfied by prose: `core/quarantine.py` passed
        on the word "quarantine" in a sentence about a quarantine
        FOLDER, `helpers/theme.py` on "theme tokens", `helpers/
        restore.py` on "restore tier". Three real modules were in no
        part of the map while the guard for that said they were.

        `dir/stem` rather than `dir/stem.py`, so that a reference like
        `core/grid_columns.COLUMNS` counts: it places the module."""
        # PACKAGE is <repo>/scripts/python/amaze, so the repo is three
        # levels up - not two, which lands in scripts/ and reads as a
        # missing map rather than a wrong path.
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
                rel = os.path.relpath(os.path.join(root, name), PACKAGE)
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
    """Qt does not dim a pixmap a widget paints itself, so each of
    these has to apply the rule by hand - and only one of the three
    did. overview.md §2 states both of the missing ones."""

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
        """_update_list_columns decides a column EXISTS from the active
        delegate's roles, so borrowing the Materials delegate gave Node
        and Code a Version column reading "none" on every row. Worse
        and latent: _open_versions_dialog maps its index through the
        MATERIAL proxy and indexes material_model.assets."""
        # RE-KEYED 2026-08-03: the delegate is DECLARED on the section
        # now, not spelled out inside an activation body in the panel -
        # which is what let the fourth delegate fall out of all three
        # sweeps. The assertion moves with it, and is stronger for it:
        # a declaration can be read without running anything.
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

    def test_the_versions_hover_reads_the_active_delegate(self):
        source = func_source("panel/panel.py", "_sync_versions_hover")
        self.assertIn(
            "self.thumblist.itemDelegate()", source,
            "the hover hit-test hard-codes the Materials delegate, "
            "which is no longer the one painting in Node or Code")


class TheOnlineGridIsFittedLikeTheOthers(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def test_a_column_is_its_DEFAULT_whenever_the_rows_land(self):
        """On a cold catalogue the online model has 0 rows when the
        view is first shown, and the catalogue lands afterwards through
        `endResetModel`.

        The bug this guards has always been the same: a column whose
        width depended on WHEN the rows arrived. It used to measure an
        empty model and fall to a 120px floor that nothing re-measured.

        Nothing measures at all now (2026-08-04) - a column starts at
        its `COLUMN_DEFAULT_WIDTH` and the user drags it - so the
        timing dependence is gone by construction, and that is what
        this asserts: the same width before and after a reset, and the
        documented default either way.

        It does NOT assert that a long name widens its column. It no
        longer does, deliberately: measuring cost 0.4ms sampled and
        13.5ms exact on every change of the row set, and re-running it
        forbade dragging - `ResizeToContents` documents that the size
        "cannot be changed by the user or programmatically". A name
        too long for its column elides, and the column can be pulled
        wider by hand.
        """
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

class OneProgressBarOwnerPerThingShown(unittest.TestCase):

    def test_the_folder_bar_is_hidden_in_the_online_world(self):
        """current_section deliberately keeps naming the LOCAL section
        while the online world shows, so the section test alone cannot
        see that the user has left."""
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
        """Reported 2026-08-04: a bar flashed on every entry to Files.

        It was a geometry pass over two filecache files that fail
        `no cookable geometry` - 45 failure records across 10 sessions
        in the debug log, roughly 75 attempts, because nothing
        remembers a failure. The bar is `hou.InterruptableOperation`,
        so it opens as soon as the pass starts: the caches have to be
        gone from the list BEFORE `total` is taken, not skipped inside
        the loop.
        """
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
        """SideFX document exactly two: the default `.bgeo.sc`, and
        `.vdb` when every primitive is a VDB volume. Longest-wins
        matching is what keeps `.bgeo.sc` from reading as `.bgeo`."""
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
    """Colour and Show All Files were added after the relocate hook and
    never joined it: the sidebar row and every tile lost their colour
    band, and every unknown file in the folder vanished with no way
    back, because the old path no longer exists to re-register.

    The hand-written tuple this used to assert against is GONE
    (2026-08-03). It was the defect wearing a name: a list held by the
    caller is a list someone can write short, and this one already had
    been - twice, by the same root, a day apart. The relocate now names
    the prefix that moved and the Keyed Store Engine walks its own
    registry, so a store cannot fail to join a list it never had to be
    added to."""

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
        """They still have to be named SOMEWHERE - once, where the
        record is DEFINED.

        Re-keyed 2026-08-05 with the move into the library: the four
        settings surfaces this asserted against are gone, so the old
        assertion would have gone vacuous rather than red. `registered`
        joins them, which is the field that had no surface of its own.
        """
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
        # Against the RECORD, not the four retired private dicts: those
        # are derived now, so asserting on them would pass by reading
        # the copy this test seeded rather than what the move produced.
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
        """The half no hand-written tuple ever had. Locate Folder
        rewrote the pointer and the four preferences and left every
        comment and every chosen icon keyed on a path that no longer
        exists - silently, and with no way to get them back."""
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
        """notes.json mixes `material:<id>` with `file:<path>` in one
        file. An asset id does not move when a folder does, and a
        rekey that did not know the difference would rewrite ids."""
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
        """Removal cleared the name and the recursion and left the
        colour and the Show All Files override behind - so re-adding
        the same folder came back amber, with unknown files showing,
        and nothing had said either was kept."""
        prefs = _location_prefs(self, {"/gone/": "Bokeh"}, {"/gone/": "#ff8000"},
                                {"/gone/": True}, ["/gone/"])
        keyed_store.retire_prefix(prefs, "/gone/")
        # The RECORD, all five fields at once. The four private dicts
        # this used to read are the seed copy, which a removal does not
        # rewrite - so they would have stayed green while the store kept
        # every one of them.
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
    """One document controls every font, the way one table already
    controls the colours - raised 2026-08-04, after list mode and the
    tiles were both found rendering wrong on Windows.

    There were four independent font rules in three files. `theme.py`
    owned `ui_px` and the colours and owned no fonts at all, so every
    size was decided where it was used and each was correct only on the
    machine it was typed on.
    """

    def test_no_module_but_theme_sizes_a_font_by_a_LITERAL(self):
        """THE GATE. A point size written as a number, anywhere but the
        table, is the thing that came back four times.

        PIXEL sizes are deliberately NOT swept in: `DesignedDialog.d()`
        and `theme.ui_px` are a separate, already-governed convention
        (practice.md ▸ *UI designs arrive as HTML*), and code previews
        pin a monospace pixel size on purpose.
        """
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
        """Decided 2026-08-05: floor on `ui_px(12)`, not a raw 12, so
        the panel follows Global UI Size the way the host scales its own
        chrome. At UI_SCALE 1.0 that IS 12, so a machine at scale 1 sees
        no change - which is exactly why it needs a test, not an eye."""
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
        """A font sized in pixels answers -1 to pointSizeF, and clamping
        that to the floor would silently convert it to points."""
        from amaze.helpers import theme as theme_mod
        pixel = QtGui.QFont()
        pixel.setPixelSize(9)
        self.assertEqual(-1, pixel.pointSize())
        self.assertEqual(9, theme_mod.ui_font(pixel).pixelSize(),
                         "a pixel-sized font was converted to points")


class PaintingTheSidebarNeverTouchesTheDisk(unittest.TestCase):

    def test_the_all_row_only_sums_what_is_already_counted(self):
        """_counts exists "so painting the sidebar never touches the
        disk", and activate() empties it - so an All row that forces a
        count per location did the whole recursive realpath walk of
        every registered tree inside data(), on the first paint after
        every activation."""
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
        """cat_list has no persistent selection model, so setModel()
        always leaves it with nothing selected. Three activates each
        carried their own copy of the fix; Materials had none, so when
        the remembered category was no longer a row the proxy kept its
        old filter while the sidebar highlighted nothing.

        RE-KEYED 2026-08-03, in the batch that moved them. The four
        bodies were in panel.py and are now two `activate()` methods on
        the Sections - one shared by Materials, Node and Code, one for
        Color. This went RED rather than vacuous when they moved, which
        is what a source-scan detector should do: `func_source` raises
        on a name it cannot find instead of scanning nothing."""
        for name in ("AssetSection.activate", "GradientSection.activate"):
            cls, method = name.split(".")
            self.assertIn(
                "_select_default_sidebar_row",
                method_source("panel/sections.py", cls, method),
                "%s establishes its default sidebar row on its own "
                "again, or not at all" % name)


class TheGridPaneIsResolvedByElimination(_PanelCase):
    """The panel no longer resolves the grid pane at all: both side
    panes hold their own width (ui_helpers.HeldPane) and the splitter
    takes the difference from the one pane that flexes. What the
    Comments pane's width does is pinned in test_comments_area.

    This remains because the CONSTRUCTION does - and it is the fact
    that made the hand-written version wrong."""

    def test_thumblist_is_not_a_pane_but_a_child_of_one(self):
        """Measured: `thumblist` is a child INSIDE the grid pane and
        never a direct child of the splitter, so any code reaching for
        `indexOf(thumblist)` gets -1 and silently falls back to
        something else - docked narrow, that was the SIDEBAR, and
        showing Comments ate the sidebar's width."""
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
        """matx_import.import_record has only try/finally, so
        build_karma_material and library.add_asset raise straight
        through it: a raise on the second of five aborted the loop and
        the "%d of %d could not be imported" dialog never appeared."""
        for name in ("_import_online_records",
                     "_import_online_records_to_scene"):
            self.assertIn(
                "except Exception", func_source("panel/panel.py", name),
                "%s abandons its batch on a raising record" % name)


class TheCommentGlyphsAreRasterisedOnce(unittest.TestCase):

    def test_the_glyph_cache_keys_on_every_input(self):
        """_paint_todo_glyphs calls this inside its block walk, and the
        text cursor repaints the viewport about twice a second - so ten
        to-dos meant ten file opens and ten SVG parses per paint."""
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
    """The construction-time accent sweep ran BEFORE the sections were
    built, and tile_delegates() is DERIVED from the sections - so it
    walked an empty tuple and every subtitle painted the class-default
    blue until Preferences was opened and closed once (whose own sweep
    runs late enough). One hand-set on the gradient delegate masked the
    hole for exactly one of five delegates."""

    def test_every_tile_delegate_wears_the_accent(self):
        """Vacuously green under a DEFAULT accent (the class default is
        itself theme-derived), so the ORDER test below is the real pin;
        this one holds the end state for whatever accent is set."""
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
        """The observable half: tile_delegates() derives from
        self.sections, so a sweep before build_sections walks an empty
        tuple - read as ORDER, because under a default accent the
        painted result cannot tell a dead sweep from a live one."""
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
    """The paint path keyed the colour lookup on the row's own
    directory, so every subfolder row of a recursive location painted
    bandless - and deep-copied a location record per tile per frame
    while doing it. The owning location resolves by prefix, once per
    FOLDER, cached."""

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
    """The no-library branch nulls six model attributes; the two File
    models were not among them, and show_prefs reads file_files_model
    unconditionally - so on a machine with no library configured the
    Preferences gear raised AttributeError, and Preferences is the only
    way to configure a library: a first-run dead end."""

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


if __name__ == "__main__":
    unittest.main()
