"""Panel, thumbnail renderer and drag engine use `hou.ui` only through a guard ▸r/status-bar"""

import ast
import os
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # before the app exists ▸p/first-app-picks-the-platform
from PySide6 import QtCore, QtWidgets  # noqa: E402

import hou  # noqa: E402

from amaze import messages, preview  # noqa: E402
from amaze.core import dragengine, library_files, material  # noqa: E402
from amaze.render import nodes, thumbs  # noqa: E402
from amaze.utils import rc_calls  # noqa: E402
from amaze.tests import test_support  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

_PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GUARDED = ("panel/panel.py", "render/thumbs.py", "core/dragengine.py",
           "utils/rc_calls.py", "prefs/prefs.py", "panel/sections.py",
           "panel/online_import.py", "panel/package_import.py",
           "panel/drop_placement.py", "panel/tile_capture.py")


def direct_hou_ui_uses(relpath):
    """(line, name) for every direct `hou.ui.<name>` use in `relpath`; `getattr` is not matched."""
    path = os.path.join(_PACKAGE, relpath)
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        inner = node.value
        if (isinstance(inner, ast.Attribute) and inner.attr == "ui"
                and isinstance(inner.value, ast.Name)
                and inner.value.id == "hou"):
            found.append((node.lineno, node.attr))
    return sorted(found)


class GuardedFilesNeverUseHouUiDirectlyTest(unittest.TestCase):
    """Fails when a direct `hou.ui` access is added to any file in GUARDED. ▸p/refuse-vs-alert"""

    def test_no_guarded_file_uses_hou_ui_directly(self):
        self.assertTrue(direct_hou_ui_uses("dialogs/repair_dialog.py"),    # ▸p/vacuous-register
                        "the scan finds no `hou.ui` access even in repair_dialog.py, "
                        "so its empty results below mean nothing")
        for relpath in GUARDED:
            with self.subTest(relpath):
                raw = direct_hou_ui_uses(relpath)
                self.assertEqual(
                    [], raw,
                    "%s uses `hou.ui` without the getattr guard "
                    "at %s" % (relpath,
                               ", ".join("%d:%s" % one for one in raw)))


class TheGuardedPanelReturnsEarlyHeadlessTest(unittest.TestCase):
    """Each method reaches its own early return instead of an AttributeError."""

    def setUp(self):
        self.assertFalse(hasattr(hou, "ui"),
                         "this host HAS a ui, so nothing here is tested")
        self.panel = test_support.fixture_panel(self)

    def test_every_guarded_function_returns_early_instead_of_crashing(self):
        """No library, no editor, no selected folder: each returns early. No network reads None."""
        panel = self.panel
        geo = hou.node("/obj").createNode("geo", "headless_convert_geo")    # no conversion route: the error message is shown
        self.addCleanup(geo.destroy)
        calls = (("open_usdlib_folder", lambda: panel.open_usdlib_folder()),
                 ("_active_network_pwd", lambda: self.assertIsNone(panel._active_network_pwd())),
                 ("locate_folder_user", lambda: panel.locate_folder_user(None)),
                 ("rc_calls.convert(None)", lambda: rc_calls.convert(None, "Karma")),
                 ("rc_calls.convert(geo)", lambda: rc_calls.convert(geo, "Karma")),
                 ("rc_calls.convert(geo, swap)", lambda: rc_calls.convert(geo, "Karma", swap=True)))
        panel.material_model = None
        for name, call in calls:
            with self.subTest(function=name):
                try:
                    call()
                except AttributeError as crash:
                    self.fail("%s called a host dialog and crashed: %s" % (name, crash))


class TheGuardStillOpensTheDialogTest(unittest.TestCase):
    """The positive case: the guard returns early only when there is no `hou.ui`."""

    def setUp(self):
        self.shown = []
        self.panel = test_support.fixture_panel(self)

    def _ui(self, **extra):
        fake = types.SimpleNamespace(
            displayMessage=self._record_message,
            setStatusMessage=lambda text, *a, **k: None,
            selectFile=lambda *a, **k: "",
            paneTabs=lambda *a, **k: (),
        )
        for name, value in extra.items():
            setattr(fake, name, value)
        return fake

    def _record_message(self, text, *_args, **_kwargs):
        self.shown.append(text)
        return 1

    def test_open_folder_still_shows_its_message_when_there_is_a_screen(self):
        self.panel.material_model = None
        with mock.patch.object(hou, "ui", self._ui(), create=True):
            self.panel.open_usdlib_folder()
        self.assertEqual(1, len(self.shown),
                         "the guard skipped the dialog in a session that "
                         "HAS a ui, which a headless-only test cannot detect")
        self.assertIn("library", self.shown[0].lower())

    def test_the_active_network_still_reads_the_pane_tabs(self):
        reads = []

        def pane_tabs(*_args, **_kwargs):
            reads.append(True)
            return ()

        with mock.patch.object(hou, "ui", self._ui(paneTabs=pane_tabs),
                               create=True):
            self.panel._active_network_pwd()
        self.assertEqual(1, len(reads),
                         "the guard skipped the pane-tab read in a session "
                         "that has a ui")


class EveryLookupFindsTheSameVisibleNetworkEditor(unittest.TestCase):
    """Current tab first, then any; the panel's two lookups and `NodeHandler` agree."""

    def test_the_three_readers_agree(self):
        panel = test_support.fixture_panel(self)

        def editor(name, current, pwd):
            return types.SimpleNamespace(
                name=name, isCurrentTab=lambda: current, pwd=lambda: pwd,
                type=lambda: hou.paneTabType.NetworkEditor)

        hidden, shown, twin = (editor("hidden", False, "/obj"),
                               editor("shown", True, "/stage"),
                               editor("twin", True, "/stage"))
        viewer = types.SimpleNamespace(type=lambda: hou.paneTabType.SceneViewer)
        ui = types.SimpleNamespace(paneTabs=lambda: [viewer, hidden, shown, twin])
        with mock.patch.object(hou, "ui", ui, create=True):
            self.assertEqual("/stage", panel._active_network_pwd())
            self.assertEqual(["/stage", "/obj"], panel._view_create_networks())
            self.assertIs(shown, nodes.NodeHandler(
                panel.prefs).get_active_network_editor())


class TheCheckReportHeadingMatchesEveryLine(unittest.TestCase):
    """The report shows before any change, so its heading must not say anything was removed."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.shown = []

    def _display_message(self, text, *_args, **kwargs):
        self.shown.append(text)
        return kwargs.get("close_choice", 0)    # Close, and Cancel on any confirm

    def test_the_heading_contains_no_removed_deleted_or_finished(self):
        mats = material.section_folder(self.panel.prefs.dir, library_files.MATERIALS)
        left = os.path.join(mats, "LEFTOVERHERE1.mat")
        with open(left, "w", encoding="utf-8") as handle:
            handle.write("in no list at all\n")    # beside an empty Node list: nothing moves
        from amaze.dialogs import repair_dialog
        screen = types.SimpleNamespace(displayMessage=self._display_message)
        with mock.patch.object(hou, "ui", screen, create=True):
            repair_dialog.check_failed_library(self.panel.prefs.dir, self.panel.prefs)
        report = self.shown[-1]
        self.assertIn("LEFTOVERHERE1.mat", report, "premise: the report did not name the file")
        self.assertTrue(os.path.exists(left), "the report moved the file it lists")
        heading = report.split("\n", 1)[0].lower()
        for claim in ("removed", "deleted", "finished"):
            self.assertNotIn(claim, heading,
                             "the report opens with %r above lines that "
                             "say otherwise" % claim)


class TheThumbnailImportFailureNeedsNoScreenTest(unittest.TestCase):
    """`create_thumbnail` stops on an asset that fails to import, inside a headless batch render."""

    def setUp(self):
        self.assertFalse(hasattr(hou, "ui"))
        self.prefs = test_support.fixture_prefs(self)
        patcher = mock.patch.object(    # the batch needs a viewer's OCIO before it imports anything
            preview, "ocio_from_viewer", lambda: {"display": "d", "view": "v", "space": "s"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _failing_import(self, *_args, **_kwargs):
        return False, "the asset file is missing on disk", None

    def _renderer(self):
        return thumbs.ThumbNailRenderer(
            self.prefs, material.Material(name="gone", mat_id="no-such-id", renderer="Karma"))

    def test_a_failed_import_does_not_crash_the_render(self):
        with mock.patch.object(nodes.NodeHandler, "import_asset_to_scene",
                               self._failing_import):
            try:
                self._renderer().create_thumbnail()
            except AttributeError as crash:
                self.fail("the failed import crashed the render: %s" % crash)

    def test_the_import_error_is_still_shown_when_there_is_a_screen(self):
        shown = []
        fake = types.SimpleNamespace(
            displayMessage=lambda text, *a, **k: shown.append(text))
        with mock.patch.object(nodes.NodeHandler, "import_asset_to_scene",
                               self._failing_import), \
                mock.patch.object(hou, "ui", fake, create=True):
            self._renderer().create_thumbnail()
        self.assertEqual(["the asset file is missing on disk"], shown)


class TheCursorLookupReturnsNoneHeadlessTest(unittest.TestCase):
    """`pane_tab_under_cursor` returns None headless instead of crashing in its fallback."""

    def setUp(self):
        self.assertFalse(hasattr(hou, "ui"),
                         "this host HAS a ui, so nothing here is tested")

    def test_the_lookup_and_the_release_target_are_none_without_a_screen(self):
        """Five callers read None as no tab; `viewport_release_target` catches no error itself."""
        for name, call in (("pane_tab_under_cursor", dragengine.pane_tab_under_cursor),
                           ("viewport_release_target",
                            lambda: dragengine.viewport_release_target(None))):
            with self.subTest(function=name):
                try:
                    answer = call()
                except AttributeError as crash:
                    self.fail("%s crashed: %s" % (name, crash))
                self.assertIsNone(answer)


class TheCursorLookupStillReadsTheScreenTest(unittest.TestCase):
    """Positive case: with `hou.ui` the lookup still returns a tab, or every drop fails silently."""

    def test_the_stock_pane_tab_under_cursor_is_used_first(self):
        tab = object()
        fake = types.SimpleNamespace(paneTabUnderCursor=lambda: tab,
                                     paneTabs=lambda: ())
        with mock.patch.object(hou, "ui", fake, create=True):
            self.assertIs(tab, dragengine.pane_tab_under_cursor())

    def test_the_geometric_fallback_still_reads_the_pane_tabs(self):
        """The fallback has the guarded `hou.ui` call; a session with a ui must still run it."""
        reads = []

        def pane_tabs():
            reads.append(True)
            return ()

        fake = types.SimpleNamespace(paneTabUnderCursor=lambda: None,
                                     paneTabs=pane_tabs)
        with mock.patch.object(hou, "ui", fake, create=True):
            dragengine.pane_tab_under_cursor()
        self.assertEqual(1, len(reads),
                         "the guard skipped the fallback in a session that "
                         "has a ui")


class ThePanelLookupReturnsNoneHeadlessTest(unittest.TestCase):
    """The right-click entry points return None headless; the four callers already skip on None."""

    def setUp(self):
        self.assertFalse(hasattr(hou, "ui"),
                         "this host HAS a ui, so nothing here is tested")

    def test_the_panel_lookup_is_none_without_a_screen(self):
        try:
            answer = rc_calls._find_panel()
        except AttributeError as crash:
            self.fail("the panel lookup crashed: %s" % crash)
        self.assertIsNone(answer)

    def test_a_right_click_save_stops_instead_of_crashing(self):
        try:
            rc_calls.save()
        except AttributeError as crash:
            self.fail("the right-click save crashed: %s" % crash)


class ThePanelLookupStillReadsTheScreenTest(unittest.TestCase):
    """Positive case: with a screen the lookup still reads pane tabs, or right-click Save fails."""

    def test_the_pane_tabs_are_still_read_when_there_is_a_screen(self):
        reads = []

        def pane_tabs():
            reads.append(True)
            return ()

        displayed = []
        fake = types.SimpleNamespace(
            paneTabs=pane_tabs,
            displayMessage=lambda text, *a, **k: displayed.append(text))
        with mock.patch.object(hou, "ui", fake, create=True):
            self.assertIsNone(rc_calls._find_panel())
        self.assertEqual(1, len(reads),
                         "the guard skipped the pane-tab read in a session "
                         "that has a ui")
        self.assertEqual(1, len(displayed),
                         "the guard swallowed the open-the-panel message in "
                         "a session that could have shown it")


def _preferences(case):
    from amaze.dialogs import prefs_window
    prefs = test_support.fixture_prefs(case)
    return prefs, prefs_window.AmazePrefsState(prefs, panel=None)


def _picked(state):
    from amaze.dialogs import prefs_window
    return state.getPref(prefs_window.LIBRARY)


class AddChangesNothingHeadlessTest(unittest.TestCase):
    """With no screen there is nobody to pick a folder, so Add changes nothing."""

    def test_add_without_a_screen_changes_nothing(self):
        self.assertFalse(hasattr(hou, "ui"),
                         "this host HAS a ui, so nothing here is tested")
        prefs, state = _preferences(self)
        before = _picked(state)
        try:
            state.addLibrary()
        except AttributeError as crash:
            self.fail("Add crashed without a screen: %s" % crash)
        self.assertEqual(before, _picked(state))


class AddOpensTheChooserTest(unittest.TestCase):
    """Clicking Add is the confirmation: the folder chooser opens first, with its own title."""

    def test_the_chooser_opens_directly_with_its_title(self):
        displayed, titles = [], []
        _prefs, state = _preferences(self)

        def select_file(*_args, **kwargs):
            titles.append(kwargs.get("title", ""))
            return ""

        fake = types.SimpleNamespace(
            displayMessage=lambda text, *a, **k: displayed.append(text),
            selectFile=select_file)
        with mock.patch.object(hou, "ui", fake, create=True):
            state.addLibrary()
        self.assertEqual([], displayed,
                         "a message was shown before the folder chooser")
        self.assertEqual([messages.TITLE_CHOOSE_LIBRARY_FOLDER], titles,
                         "the chooser opened without its title")


class TheRootOfADiskIsNoLibraryTest(unittest.TestCase):
    """A disk's root picked with Add is refused, and the Library list does not show it."""

    def test_the_root_shows_library_path_invalid_and_is_not_added(self):
        displayed = []
        prefs, state = _preferences(self)
        before = _picked(state)
        fake = types.SimpleNamespace(
            displayMessage=lambda text, *a, **k: displayed.append(text),
            selectFile=lambda *a, **k: os.path.abspath(os.sep))
        with mock.patch.object(hou, "ui", fake, create=True):
            state.addLibrary()
        self.assertEqual([messages.LIBRARY_PATH_INVALID], displayed,
                         "the root was accepted without a message")
        self.assertEqual(before, _picked(state),
                         "the root of the disk is shown as a library")
        self.assertEqual(before, prefs.dir, "a refused pick moved the library")


class EveryDialogSubclassesAssetDialogTest(unittest.TestCase):
    """Every QDialog in dialogs/ subclasses AssetDialog or gives a reason in HOUSE_STRAY."""

    def test_every_dialog_class_subclasses_asset_dialog_or_is_in_house_stray(self):
        import importlib
        import pkgutil

        from amaze import dialogs as dialogs_pkg
        from amaze.dialogs.base_dialog import AssetDialog

        strays = []
        seen = 0
        for info in pkgutil.iter_modules(dialogs_pkg.__path__):
            module = importlib.import_module("amaze.dialogs." + info.name)
            for name, value in vars(module).items():
                if not (isinstance(value, type)
                        and issubclass(value, QtWidgets.QDialog)
                        and value.__module__ == module.__name__):
                    continue
                seen += 1
                if issubclass(value, AssetDialog):
                    continue
                if isinstance(getattr(value, "HOUSE_STRAY", None), str):
                    continue
                strays.append("%s.%s" % (module.__name__, name))
        self.assertGreaterEqual(
            seen, 5, "the walk found almost no dialog classes, so it is "
                     "not scanning the package it thinks it is")
        self.assertEqual(
            [], strays,
            "these dialogs neither subclass AssetDialog nor record a reason "
            "in HOUSE_STRAY, so the next style or sizing fix silently "
            "misses them: %s" % strays)


class TheMaterialSaveUsesTheClickedNodeTest(unittest.TestCase):
    """Right-click Save on a material saves the clicked node, which is made the selection."""

    def setUp(self):
        mat = hou.node("/mat")
        self.a = mat.createNode("materialbuilder", "click_node")
        self.b = mat.createNode("materialbuilder", "other_node")
        self.addCleanup(self.a.destroy)
        self.addCleanup(self.b.destroy)
        self.panel = mock.Mock()
        patcher = mock.patch.object(rc_calls, "_find_panel",
                                    return_value=self.panel)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_an_unselected_clicked_node_becomes_the_selection(self):
        self.b.setSelected(True, clear_all_selected=True)   # the premise set explicitly: createNode selects what it creates
        rc_calls.save(self.a)
        self.assertTrue(self.a.isSelected(),
                        "the clicked node was not selected")
        self.assertFalse(
            self.b.isSelected(),
            "the save would have followed the selection, not the click - "
            "the bug rc_calls.save exists to prevent")
        self.panel.save_from_node.assert_called_once_with(self.a)

    def test_a_click_inside_a_multi_selection_keeps_it(self):
        self.a.setSelected(True, clear_all_selected=True)
        self.b.setSelected(True)
        rc_calls.save(self.a)
        self.assertTrue(
            self.a.isSelected() and self.b.isSelected(),
            "multi-save is a feature - a click inside the selection "
            "must not shrink it")
        self.panel.save_from_node.assert_called_once_with(self.a)

    def test_no_node_still_saves_the_selection(self):
        rc_calls.save()
        self.panel.save_from_node.assert_called_once_with(None)


class EveryDialogKnowsWhichWindowOpenedIt(unittest.TestCase):
    """A dialog built with a parent opens on its parent's screen, not the primary ▸r/dialog-parents"""

    DIALOGS = {"NameDialog", "CategoryDialog",
               "SaveDialog", "CodeDialog",
               "IconDialog", "VersionsDialog"}

    EXEMPT = set()

    def _package_root(self):
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _constructions(self):
        """(relative path, line, dialog name, passes_a_parent) for every dialog built outside the tests."""
        root = self._package_root()
        found = []
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs
                       if d not in ("__pycache__", "tests")]
            for filename in files:
                if not filename.endswith(".py"):
                    continue
                path = os.path.join(dirpath, filename)
                with open(path, "r", encoding="utf-8") as handle:
                    tree = ast.parse(handle.read())
                relative = os.path.relpath(path, root).replace(os.sep, "/")    # EXEMPT is spelled with `/` on every OS
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    name = (node.func.attr
                            if isinstance(node.func, ast.Attribute)
                            else getattr(node.func, "id", ""))
                    if name not in self.DIALOGS:
                        continue
                    keywords = {k.arg for k in node.keywords}
                    parented = (
                        "parent" in keywords
                        or (name == "IconDialog" and len(node.args) >= 3))
                    found.append((relative, node.lineno, name, parented))
        return found

    def test_no_dialog_is_built_without_a_parent(self):
        found = self._constructions()
        self.assertGreaterEqual(    # ▸p/vacuous-register
            len(found), 6,
            "the dialog scan found %d construction sites - it has stopped "
            "matching, so its empty result means nothing" % len(found))
        offenders = [
            "%s:%d %s" % (path, line, name)
            for path, line, name, parented in found
            if not parented and (path, name) not in self.EXEMPT
        ]
        self.assertEqual(
            [], offenders,
            "these dialogs are built with no parent, so they open on the "
            "primary screen rather than on the panel that opened them: %s"
            % ", ".join(offenders))

    def test_every_dialog_class_accepts_a_parent(self):
        """Every dialog class accepts a parent and passes it on to `super().__init__`."""
        import inspect
        from amaze.dialogs import (base_dialog, code_dialog, gradient_dialog,
                                   icon_dialog, save_dialog)
        classes = [base_dialog.AssetDialog, base_dialog.NameDialog,
                   gradient_dialog.CategoryDialog, code_dialog.CodeDialog,
                   icon_dialog.IconDialog, save_dialog.SaveDialog]
        for cls in classes:
            args = inspect.signature(cls.__init__).parameters
            self.assertIn(
                "parent", args,
                "%s cannot be given a parent at all" % cls.__name__)

    def test_a_parent_really_does_decide_the_screen(self):
        """The premise, measured: a parented dialog inherits its parent's screen in Qt."""
        host = QtWidgets.QWidget()
        self.addCleanup(host.deleteLater)
        parented = QtWidgets.QDialog(host)
        self.addCleanup(parented.deleteLater)
        self.assertIs(
            parented.screen(), host.screen(),
            "a parented dialog no longer inherits its parent's screen")


class EverySectionUsesSaveDialog(unittest.TestCase):
    """Every section uses SaveDialog; a multi-selection disables the Name row, never removes it."""

    def _dialog(self, **kwargs):
        from amaze.dialogs import save_dialog
        dialog = save_dialog.SaveDialog(["Metal"], "Metal", **kwargs)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_the_name_row_is_built_empty_or_prefilled(self):
        dialog = self._dialog()
        self.assertIsNotNone(
            dialog.line_name,
            "the dialog has no Name row, so this section saves "
            "through a different form than its siblings")
        self.assertEqual("", dialog.line_name.text())
        self.assertTrue(dialog.line_name.isEnabled())
        self.assertEqual("rocks1", self._dialog(name="rocks1").line_name.text())

    def test_a_multi_selection_greys_the_name_row_instead(self):
        dialog = self._dialog(name="", name_enabled=False)
        self.assertIsNotNone(
            dialog.line_name,
            "the disabled form has no Name row, so the dialog changes "
            "SHAPE between one material and several")
        self.assertFalse(
            dialog.line_name.isEnabled(),
            "the Name field is enabled for a multi-selection, where one "
            "name cannot serve several assets")

    def test_only_an_enabled_name_field_is_read(self):
        """A disabled field's text would rename a whole multi-selection to one string."""
        for enabled, typed, harvested in ((False, "typed anyway", ""), (True, "renamed", "renamed")):
            with self.subTest(enabled=enabled):
                dialog = self._dialog(name="" if not enabled else "rocks1", name_enabled=enabled)
                dialog.line_name.setText(typed)
                dialog._on_accept()
                self.assertEqual(harvested, dialog.name)

    def test_the_category_is_picked_never_typed(self):
        """A non-editable dropdown, like Language: new categories come from the sidebar's Add."""
        self.assertFalse(
            self._dialog().combo_cats.isEditable(),
            "the category combo accepts typing, and the app's only place "
            "to create a category is the sidebar's Add")

    def test_the_title_is_save_to_app_name_unless_a_caller_passes_one(self):
        from amaze import branding
        self.assertEqual("Save to " + branding.APP_NAME,
                         self._dialog().windowTitle())
        self.assertEqual("Save Gradient",
                         self._dialog(title="Save Gradient").windowTitle())


class TheSaveDialogsHaveTheDrawnWidth(unittest.TestCase):
    """The save dialogs share one drawn width, measured after `show()` ▸r/fixed-size-constraint"""

    def _shown(self, dialog):
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        QtWidgets.QApplication.processEvents()
        self.addCleanup(dialog.hide)
        return dialog

    def _dialogs(self):
        """D09 is the save frame: greyed and titled forms share its three rows ▸p/one-design-document"""
        from amaze import branding
        from amaze.dialogs import gradient_dialog, save_dialog
        return (
            ("D09 Save to Amaze (Node)",
             save_dialog.SaveDialog(["Metal"], "Metal", name="rocks1")),
            ("D09 Save to Amaze (Materials)",
             save_dialog.SaveDialog(["Metal"], "Metal", name="",
                                    name_enabled=False)),
            ("D09 Save Gradient to Amaze",
             save_dialog.SaveDialog(["Warm"], "Warm", name="sunset",
                                    title="Save Gradient to "
                                          + branding.APP_NAME)),
            ("D13 Name Input",
             gradient_dialog.CategoryDialog()),
        )

    def test_every_dialog_in_the_package_can_actually_be_BUILT(self):
        """Every dialog in the package can be constructed, not only read as source."""
        from amaze import amazetheme
        from amaze.dialogs import (base_dialog, code_dialog, gradient_dialog,
                                   icon_dialog, save_dialog)
        from amaze.helpers import theme
        built = (
            ("SaveDialog", lambda: save_dialog.SaveDialog(["Metal"], "Metal")),
            ("CategoryDialog", gradient_dialog.CategoryDialog),
            ("NameDialog", base_dialog.NameDialog),
            ("CodeDialog", lambda: code_dialog.CodeDialog(["Metal"])),
            ("IconDialog", icon_dialog.IconDialog),
        )
        for name, build in built:
            with self.subTest(dialog=name):
                dialog = build()
                self.addCleanup(dialog.deleteLater)
                dialog.show()
                QtWidgets.QApplication.processEvents()
                self.addCleanup(dialog.hide)
                self.assertGreater(dialog.width(), 0,
                                   "%s built with no width" % name)
        code = code_dialog.CodeDialog(["Metal"])
        self.addCleanup(code.deleteLater)
        code.show()
        QtWidgets.QApplication.processEvents()
        self.addCleanup(code.hide)
        self.assertGreaterEqual(
            code.width(), theme.ui_px(amazetheme.D11_FORM_WIDTH),
            "the code dialog opens narrower than the design's minimum width")
        self.assertLess(    # the drawn 2x2: the editor spans the full width, left of the indented Name field
            code._editor.mapTo(code, QtCore.QPoint(0, 0)).x(),
            code._line_name.mapTo(code, QtCore.QPoint(0, 0)).x(),
            "the editor sits in the field column, not across the dialog")
        self.assertGreater(
            code._combo_category.mapTo(code, QtCore.QPoint(0, 0)).x(),
            code._line_name.mapTo(code, QtCore.QPoint(0, 0)).x()
            + code._line_name.width(),
            "Category is not in a second column beside Name")
        caption = [c for c in code._editor.children()
                   if isinstance(c, QtWidgets.QLabel)]
        self.assertEqual(
            [], caption,
            "a caption is drawn on the editor; the design has none")

    def test_only_the_code_dialog_has_a_header_band(self):
        """D11 has a header band; D01, D02 and the save dialogs do not."""
        from amaze.dialogs import code_dialog, gradient_dialog, icon_dialog, save_dialog
        wants = (
            ("D02 Customize", lambda: icon_dialog.IconDialog(
                None, 0.0, None, tile_name="rocks1"), False),
            ("D11 Save Code",
             lambda: code_dialog.CodeDialog(["Metal"]), True),
            ("D09 Save", lambda: save_dialog.SaveDialog(
                ["Metal"], "Metal", name="rocks1"), False),
            ("D09 Gradient", lambda: save_dialog.SaveDialog(
                ["Warm"], "Warm", name="sunset",
                title="Save Gradient"), False),
            ("D13 Name", gradient_dialog.CategoryDialog, False),
        )
        for label, build, wanted in wants:
            with self.subTest(dialog=label):
                dialog = self._shown(build())
                band = dialog.findChild(QtWidgets.QWidget,
                                        "amaze_header_band")
                self.assertEqual(
                    wanted, band is not None,
                    "%s %s a header band" % (
                        label, "has lost" if wanted else "has grown"))

    def test_the_code_dialog_band_shows_the_SNIPPET_name(self):
        """The window title is a verb, so the band shows the name field, or `Untitled` while empty."""
        from amaze import amazetheme
        from amaze.dialogs import code_dialog
        for tag, name, expect in (
                ("new", "", amazetheme.BAND_UNTITLED),
                ("named", "helper", "helper")):
            with self.subTest(snippet=tag):
                dialog = self._shown(
                    code_dialog.CodeDialog(["Metal"], name=name))
                self.assertEqual([expect], dialog._tabbar.names(),
                                 "the band's tab does not name the snippet")

    def test_the_save_dialogs_render_ONE_width_whatever_that_width_is(self):
        """Four dialogs reading one constant render one width ▸p/shared-means-it-fails-together"""
        seen = {}
        for label, dialog in self._dialogs():
            seen[label] = self._shown(dialog).width()
        self.assertEqual(
            1, len(set(seen.values())),
            "the save dialogs render %d different widths, so they are "
            "not sharing one: %s"
            % (len(set(seen.values())),
               ", ".join("%s=%d" % kv for kv in sorted(seen.items()))))

    def test_every_one_of_them_is_the_shared_width_on_screen(self):
        from amaze import amazetheme
        from amaze.helpers import theme
        want = theme.ui_px(amazetheme.SAVE_WIDTH)
        for label, dialog in self._dialogs():
            with self.subTest(dialog=label):
                shown = self._shown(dialog)
                self.assertEqual(
                    want, shown.width(),
                    "%s renders %dpx wide, not the drawn %d - the save "
                    "family no longer shares one width"
                    % (label, shown.width(), want))

    def test_every_field_is_the_drawn_field_width(self):
        from amaze.helpers import theme
        for label, dialog in self._dialogs():
            with self.subTest(dialog=label):
                shown = self._shown(dialog)
                want = theme.ui_px(shown.FIELD_WIDTH)
                fields = [w for w in shown.findChildren(QtWidgets.QWidget)
                          if isinstance(w, (QtWidgets.QLineEdit,
                                            QtWidgets.QComboBox))
                          and w.parent() is shown]
                self.assertTrue(fields, "%s built no fields at all" % label)
                for field in fields:
                    self.assertEqual(
                        want, field.width(),
                        "%s draws a %s %dpx wide, not the drawn %d"
                        % (label, type(field).__name__, field.width(), want))

    def test_the_width_is_kept_through_a_second_layout_pass(self):
        """The width survives a later activation: a re-show, a font change or a re-polish."""
        from amaze import amazetheme
        from amaze.dialogs import save_dialog
        from amaze.helpers import theme
        want = theme.ui_px(amazetheme.SAVE_WIDTH)
        dialog = self._shown(
            save_dialog.SaveDialog(["Metal"], "Metal", name="rocks1"))
        dialog.layout().activate()
        dialog.adjustSize()
        QtWidgets.QApplication.processEvents()
        self.assertEqual(
            want, dialog.width(),
            "the width was right on show and then shrank to %d on the next "
            "layout pass" % dialog.width())


class AnAnsweredDialogIsDeletedFromItsParent(unittest.TestCase):
    """A modal dialog parented to the panel lives as long as the panel unless deleted. ▸r/menu-lifetime"""

    BUILDERS = {    # every modal the panel and Preferences open with exec()
        "save": lambda parent: __import__(
            "amaze.dialogs.save_dialog", fromlist=["_"]).SaveDialog(
                ["Metal"], "Metal", name="rocks1", parent=parent),
        "code": lambda parent: __import__(
            "amaze.dialogs.code_dialog", fromlist=["_"]).CodeDialog(
                ["Metal"], name="snippet", parent=parent),
        "category": lambda parent: __import__(
            "amaze.dialogs.gradient_dialog", fromlist=["_"]).CategoryDialog(
                parent=parent),
    }

    def _parent(self):
        parent = QtWidgets.QWidget()
        self.addCleanup(parent.deleteLater)
        return parent

    def _answer(self, dialog, answer):
        QtCore.QTimer.singleShot(0, answer)
        return dialog.exec()

    def test_three_opens_of_each_leave_no_dialog_alive(self):
        for label, build in self.BUILDERS.items():
            with self.subTest(dialog=label):
                parent = self._parent()
                for _ in range(3):
                    dialog = build(parent)
                    self._answer(dialog, dialog.reject)
                _app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)    # ▸r/deferred-delete
                self.assertEqual(
                    [], parent.findChildren(QtWidgets.QDialog),
                    "every answered %s dialog stays a live child of its "
                    "parent for the whole session" % label)

    def test_the_typed_name_is_kept_after_the_dialog_is_deleted(self):
        from amaze.dialogs import gradient_dialog
        dialog = gradient_dialog.CategoryDialog(default="Cobalt", parent=self._parent())
        dialog._line_name.setText("  Sienna ")
        self._answer(dialog, dialog._on_accept)
        _app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        self.assertEqual((False, "Sienna"), (dialog.canceled, dialog.name),
                         "the typed name was lost when the widgets were deleted")


if __name__ == "__main__":
    unittest.main()
