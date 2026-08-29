"""The panel, the thumbnail renderer and the drag engine reach the host's dialogs only through a guard, so a refusal raised with no screen present stays a refusal. ▸r/status-bar"""

import ast
import os
import tempfile
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # BEFORE the app exists: the first module to build the QApplication picks the Qt platform for the whole hython, and on the native one the host style lays widgets outside their layout cells - which fails OTHER modules' geometry asserts, three modules later ▸p/first-app-picks-the-platform
from PySide6 import QtCore, QtWidgets  # noqa: E402

import hou  # noqa: E402

from amaze.core import dragengine, material  # noqa: E402
from amaze.render import nodes, thumbs  # noqa: E402
from amaze.utils import rc_calls  # noqa: E402
from amaze.tests import test_support  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

_PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GUARDED = ("panel/panel.py", "render/thumbs.py", "core/dragengine.py",
           "utils/rc_calls.py", "prefs/prefs.py")


def raw_reaches(relpath):
    """(line, call) for every host dialog spelled straight into the source of `relpath`. The guarded spelling reads the name through `getattr` and does not match."""
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


class TheseFilesNeverSpellTheHostDialogTest(unittest.TestCase):
    """Red when a new raw reach is written into either file. ▸p/refusal-sink"""

    def test_no_guarded_file_reaches_the_host_dialogs_directly(self):
        for relpath in GUARDED:
            with self.subTest(relpath):
                raw = raw_reaches(relpath)
                self.assertEqual(
                    [], raw,
                    "%s reaches the host dialogs without the getattr guard "
                    "at %s" % (relpath,
                               ", ".join("%d:%s" % one for one in raw)))

    def test_the_reader_finds_a_reach_when_there_is_one(self):
        """A reader that answered empty to everything would pass the test above with the mechanism deleted. ▸p/vacuous-register"""
        found = raw_reaches("core/repair.py")
        self.assertTrue(found,
                        "the reader found no reach in the repair shelf tool, "
                        "which is full of them - so an empty answer above "
                        "means nothing")


class TheGuardedPanelRefusesHeadlessTest(unittest.TestCase):
    """Each method reaches its own early return instead of an AttributeError."""

    def setUp(self):
        self.assertFalse(hasattr(hou, "ui"),
                         "this host HAS a ui, so nothing here is tested")
        self.panel = test_support.fixture_panel(self)

    def test_cleanup_db_says_no_library_without_a_screen(self):
        self.panel.material_model = None
        try:
            self.panel.cleanup_db()
        except AttributeError as crash:
            self.fail("the refusal reached the host dialog and became a "
                      "crash: %s" % crash)

    def test_open_usdlib_folder_says_no_library_without_a_screen(self):
        self.panel.material_model = None
        try:
            self.panel.open_usdlib_folder()
        except AttributeError as crash:
            self.fail("the refusal reached the host dialog and became a "
                      "crash: %s" % crash)

    def test_the_active_network_is_none_when_no_screen_can_be_asked(self):
        """None is the answer this method already documents for having no editor to read."""
        try:
            answer = self.panel._active_network_pwd()
        except AttributeError as crash:
            self.fail("reading the active network became a crash: %s" % crash)
        self.assertIsNone(answer)

    def test_locating_a_folder_stops_before_the_picker(self):
        """With no row selected the refusal fires before the folders model is read, so None is a fair stand-in for it."""
        try:
            self.panel._locate_folder_user(None)
        except AttributeError as crash:
            self.fail("the folder picker became a crash: %s" % crash)


class TheGuardStillOpensTheDialogTest(unittest.TestCase):
    """The accept path: a guard proven to fire is half a guard until something proves it fires only when it should."""

    def setUp(self):
        self.shown = []
        self.panel = test_support.fixture_panel(self)

    def _ui(self, **extra):
        fake = types.SimpleNamespace(
            displayMessage=self._say,
            setStatusMessage=lambda text, *a, **k: None,
            selectFile=lambda *a, **k: "",
            paneTabs=lambda *a, **k: (),
        )
        for name, value in extra.items():
            setattr(fake, name, value)
        return fake

    def _say(self, text, *_args, **_kwargs):
        self.shown.append(text)
        return 1

    def test_cleanup_db_still_says_it_when_there_is_a_screen(self):
        self.panel.material_model = None
        with mock.patch.object(hou, "ui", self._ui(), create=True):
            self.panel.cleanup_db()
        self.assertEqual(1, len(self.shown),
                         "the guard swallowed the dialog in a session that "
                         "HAS a ui, which a headless-only test cannot see")
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


class TheThumbnailRefusalNeedsNoScreenTest(unittest.TestCase):
    """`create_thumbnail` refuses an asset that will not import, and that runs inside a headless batch render."""

    def setUp(self):
        self.assertFalse(hasattr(hou, "ui"))
        self.prefs = test_support.fixture_prefs(self)

    def _refusing_import(self, *_args, **_kwargs):
        return False, "the asset file is missing on disk", None

    def _renderer(self):
        return thumbs.ThumbNailRenderer(
            self.prefs, material.Material(name="gone", mat_id="no-such-id"))

    def test_a_refused_import_does_not_crash_the_render(self):
        with mock.patch.object(nodes.NodeHandler, "import_asset_to_scene",
                               self._refusing_import):
            try:
                self._renderer().create_thumbnail()
            except AttributeError as crash:
                self.fail("the render's refusal became a crash: %s" % crash)

    def test_the_refusal_is_still_shown_when_there_is_a_screen(self):
        shown = []
        fake = types.SimpleNamespace(
            displayMessage=lambda text, *a, **k: shown.append(text))
        with mock.patch.object(nodes.NodeHandler, "import_asset_to_scene",
                               self._refusing_import), \
                mock.patch.object(hou, "ui", fake, create=True):
            self._renderer().create_thumbnail()
        self.assertEqual(["the asset file is missing on disk"], shown)


class TheCursorLookupRefusesHeadlessTest(unittest.TestCase):
    """The picking door answers None instead of crashing in the fallback that the shelter above it walks straight into."""

    def setUp(self):
        self.assertFalse(hasattr(hou, "ui"),
                         "this host HAS a ui, so nothing here is tested")

    def test_the_pane_tab_under_the_cursor_is_none_without_a_screen(self):
        """None is what all five callers already read as `no tab under the cursor`."""
        try:
            answer = dragengine.pane_tab_under_cursor()
        except AttributeError as crash:
            self.fail("the cursor lookup became a crash: %s" % crash)
        self.assertIsNone(answer)

    def test_the_release_target_is_none_without_a_screen(self):
        """The release pick reads the lookup through `_scene_viewer_under_cursor`, which catches nothing on the way back up."""
        try:
            answer = dragengine.viewport_release_target(None)
        except AttributeError as crash:
            self.fail("the release pick became a crash: %s" % crash)
        self.assertIsNone(answer)


class TheCursorLookupStillReadsTheScreenTest(unittest.TestCase):
    """The accept path: a lookup that answered None in a session that HAS a ui would break every drop, silently."""

    def test_the_stock_hit_test_answers_first(self):
        tab = object()
        fake = types.SimpleNamespace(paneTabUnderCursor=lambda: tab,
                                     paneTabs=lambda: ())
        with mock.patch.object(hou, "ui", fake, create=True):
            self.assertIs(tab, dragengine.pane_tab_under_cursor())

    def test_the_geometric_fallback_still_reads_the_pane_tabs(self):
        """The fallback holds the reach the guard covers, so a session that has a ui must still enter it."""
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


class TheFocusKeeperNeedsNoScreenTest(unittest.TestCase):
    """The capture has nothing to ask with no ui present, and still asks when there is one - the half that catches an over-guard."""

    def test_the_focus_keeper_runs_without_a_screen(self):
        try:
            with dragengine.keep_editor_focus():
                pass
        except AttributeError as crash:
            self.fail("keeping the editor focus became a crash: %s" % crash)

    def test_the_focus_keeper_still_reads_the_pane_tabs(self):
        reads = []

        def pane_tabs():
            reads.append(True)
            return ()

        with mock.patch.object(hou, "ui",
                               types.SimpleNamespace(paneTabs=pane_tabs),
                               create=True):
            with dragengine.keep_editor_focus():
                pass
        self.assertEqual(1, len(reads),
                         "the capture skipped the pane-tab read in a session "
                         "that has a ui")


class ThePanelLookupRefusesHeadlessTest(unittest.TestCase):
    """The right-click entry points answer None instead of crashing, and the four callers already skip on None."""

    def setUp(self):
        self.assertFalse(hasattr(hou, "ui"),
                         "this host HAS a ui, so nothing here is tested")

    def test_the_panel_lookup_is_none_without_a_screen(self):
        try:
            answer = rc_calls._find_panel()
        except AttributeError as crash:
            self.fail("the panel lookup became a crash: %s" % crash)
        self.assertIsNone(answer)

    def test_a_right_click_save_stops_instead_of_crashing(self):
        try:
            rc_calls.save_material()
        except AttributeError as crash:
            self.fail("the right-click save became a crash: %s" % crash)


class ThePanelLookupStillReadsTheScreenTest(unittest.TestCase):
    """The accept path: a lookup that always answered None would break every right-click save in a real session."""

    def test_the_pane_tabs_are_still_read_when_there_is_a_screen(self):
        reads = []

        def pane_tabs():
            reads.append(True)
            return ()

        said = []
        fake = types.SimpleNamespace(
            paneTabs=pane_tabs,
            displayMessage=lambda text, *a, **k: said.append(text))
        with mock.patch.object(hou, "ui", fake, create=True):
            self.assertIsNone(rc_calls._find_panel())
        self.assertEqual(1, len(reads),
                         "the guard skipped the pane-tab read in a session "
                         "that has a ui")
        self.assertEqual(1, len(said),
                         "the guard swallowed the open-the-panel message in "
                         "a session that could have shown it")


class TheLibraryPickerRefusesHeadlessTest(unittest.TestCase):
    """With no screen there is nobody to pick a folder, so the ASK is skipped - while a library that is already set up must still be saved."""

    def setUp(self):
        self.assertFalse(hasattr(hou, "ui"),
                         "this host HAS a ui, so nothing here is tested")
        self.prefs = test_support.fixture_prefs(self)

    def test_a_missing_library_cannot_be_asked_for(self):
        self.prefs._directory = os.path.join(tempfile.gettempdir(),
                                             "amaze_no_such_library_dir")
        try:
            answer = self.prefs.get_dir_from_user()
        except AttributeError as crash:
            self.fail("the library picker became a crash: %s" % crash)
        self.assertFalse(answer)

    def test_an_existing_library_is_still_accepted_without_a_screen(self):
        """The branch that accepts a library never touches the host dialogs, so a guard on the FUNCTION would turn this into a silent no-op the suite could not see."""
        try:
            answer = self.prefs.get_dir_from_user()
        except AttributeError as crash:
            self.fail("accepting a set-up library became a crash: %s" % crash)
        self.assertTrue(answer,
                        "a library that is already set up was refused "
                        "because there was no screen to ask at")


class TheLibraryPickerStillAsksWhenThereIsAScreenTest(unittest.TestCase):
    """The accept path: the picker must still open where a person can answer it."""

    def test_the_picker_opens_when_there_is_a_screen(self):
        picked = []
        prefs = test_support.fixture_prefs(self)
        prefs._directory = os.path.join(tempfile.gettempdir(),
                                        "amaze_no_such_library_dir")

        def select_file(*_args, **_kwargs):
            picked.append(True)
            return ""

        fake = types.SimpleNamespace(
            displayMessage=lambda text, *a, **k: None,
            selectFile=select_file)
        with mock.patch.object(hou, "ui", fake, create=True):
            prefs.get_dir_from_user()
        self.assertTrue(picked,
                        "the guard skipped the folder picker in a session "
                        "that has a ui")

    def test_the_picker_opens_directly_and_carries_its_own_context(self):
        """The click that opens the picker is the consent, so nothing speaks first - the set-up preamble was a dialog in front of the dialog the gesture asked for ▸p/dialogs-are-a-bill. The context it carried moved into the picker's own title, which first launch still needs."""
        said = []
        titles = []
        prefs = test_support.fixture_prefs(self)
        prefs._directory = os.path.join(tempfile.gettempdir(),
                                        "amaze_no_such_library_dir")

        def select_file(*_args, **kwargs):
            titles.append(kwargs.get("title", ""))
            return ""

        fake = types.SimpleNamespace(
            displayMessage=lambda text, *a, **k: said.append(text),
            selectFile=select_file)
        with mock.patch.object(hou, "ui", fake, create=True):
            prefs.get_dir_from_user()
        self.assertEqual([], said,
                         "a message interrupted on the way to the folder "
                         "picker")
        self.assertTrue(titles and titles[0],
                        "the picker opened without a title, so a first "
                        "launch shows an unlabelled folder chooser")


class TheThirdPickIsStillValidatedTest(unittest.TestCase):
    """The picker allows three attempts, and every one of them counts - a valid folder picked on the last attempt must be saved, not adopted in memory and reported as a cancel."""

    def test_a_valid_third_pick_is_accepted_and_saved(self):
        prefs = test_support.fixture_prefs(self)
        good = prefs.dir
        prefs._directory = os.path.join(tempfile.gettempdir(),
                                        "amaze_no_such_library_dir")
        picks = iter(["/no/such/place", "/still/no/such/place", good])
        saved = []
        prefs.save = lambda: saved.append(True)

        fake = types.SimpleNamespace(
            displayMessage=lambda text, *a, **k: None,
            selectFile=lambda *a, **k: next(picks))
        with mock.patch.object(hou, "ui", fake, create=True):
            answer = prefs.get_dir_from_user()

        self.assertTrue(answer,
                        "a valid folder picked on the third attempt was "
                        "reported as a cancel")
        self.assertTrue(saved,
                        "the third pick was adopted in memory but never "
                        "saved - next launch is unconfigured again")


class EveryDialogRidesTheHouseShellTest(unittest.TestCase):
    """ROADMAP R51: ONE shell owner. Every QDialog subclass in dialogs/ either rides AssetDialog or names its recorded reason in a HOUSE_STRAY class attribute - the four one-off dialogs hand-copied the shell line by line before this pin existed."""

    def test_every_dialog_class_is_based_or_excused(self):
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
            "these dialogs neither ride AssetDialog nor record a reason "
            "in HOUSE_STRAY, so the next style or sizing fix silently "
            "misses them: %s" % strays)


class TheMaterialDoorFollowsTheClickTest(unittest.TestCase):
    """ROADMAP R50: right-click Save on a material saves the CLICKED node - the flow stays selection-based because multi-selection saves are a feature, so the door bridges the click into the selection the way its three siblings pass the node straight through."""

    def setUp(self):
        mat = hou.node("/mat")
        self.a = mat.createNode("materialbuilder", "door_click")
        self.b = mat.createNode("materialbuilder", "door_other")
        self.addCleanup(self.a.destroy)
        self.addCleanup(self.b.destroy)
        self.panel = mock.Mock()
        patcher = mock.patch.object(rc_calls, "_find_panel",
                                    return_value=self.panel)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_an_unselected_clicked_node_becomes_the_selection(self):
        self.b.setSelected(True, clear_all_selected=True)   # the premise is set EXPLICITLY - createNode selects what it creates, so trusting the post-create state would test the wrong selection
        rc_calls.save_material(self.a)
        self.assertTrue(self.a.isSelected(),
                        "the clicked node never entered the selection")
        self.assertFalse(
            self.b.isSelected(),
            "the save would have followed the selection, not the click - "
            "the bug this door exists to prevent")
        self.panel.save_asset.assert_called_once_with()

    def test_a_click_inside_a_multi_selection_keeps_it(self):
        self.a.setSelected(True, clear_all_selected=True)
        self.b.setSelected(True)
        rc_calls.save_material(self.a)
        self.assertTrue(
            self.a.isSelected() and self.b.isSelected(),
            "multi-save is a feature - a click inside the selection "
            "must not shrink it")
        self.panel.save_asset.assert_called_once_with()

    def test_no_node_still_saves_the_selection(self):
        rc_calls.save_material()
        self.panel.save_asset.assert_called_once_with()


class EveryDialogKnowsWhichWindowOpenedIt(unittest.TestCase):
    """A parented dialog inherits its parent's SCREEN; a parentless one goes to the primary. With the panel torn off to another monitor that is the wrong one. ▸r/dialog-parents"""

    DIALOGS = {"NameDialog", "CategoryDialog",
               "SaveDialog", "CodeDialog", "UserPickerDialog",
               "IconDialog", "PrefsDialog", "DesignedDialog"}

    EXEMPT = {("panel/panel.py", "PrefsDialog")}    # parented to the main window AFTER construction and kept NON-modal on purpose ▸r/dialog-parents

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
                relative = os.path.relpath(path, root)
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
                        or (name == "IconDialog" and len(node.args) >= 3)
                        or (name == "DesignedDialog" and bool(node.args)))
                    found.append((relative, node.lineno, name, parented))
        return found

    def test_the_scan_actually_finds_the_dialogs(self):
        """A scan that matches nothing would pass forever. ▸p/vacuous-register"""
        found = self._constructions()
        self.assertGreaterEqual(
            len(found), 8,
            "the dialog scan found %d construction sites - it has stopped "
            "matching, so its silence means nothing" % len(found))

    def test_no_dialog_is_built_without_a_parent(self):
        offenders = [
            "%s:%d %s" % (path, line, name)
            for path, line, name, parented in self._constructions()
            if not parented and (path, name) not in self.EXEMPT
        ]
        self.assertEqual(
            [], offenders,
            "these dialogs are built with no parent, so they open on the "
            "primary screen rather than on the panel that opened them: %s"
            % ", ".join(offenders))

    def test_every_dialog_class_accepts_a_parent(self):
        """`NameDialog` could not take one at all - it called `super().__init__(title)` and dropped the argument."""
        import inspect
        from amaze.dialogs import (base_dialog, code_dialog, gradient_dialog,
                                   icon_dialog, save_dialog, user_dialog)
        classes = [base_dialog.AssetDialog, base_dialog.NameDialog,
                   gradient_dialog.CategoryDialog, code_dialog.CodeDialog,
                   icon_dialog.IconDialog, save_dialog.SaveDialog,
                   user_dialog.UserPickerDialog]
        for cls in classes:
            args = inspect.signature(cls.__init__).parameters
            self.assertIn(
                "parent", args,
                "%s cannot be given a parent at all" % cls.__name__)

    def test_a_parent_really_does_decide_the_screen(self):
        """The premise, measured - if Qt ever stops inheriting the parent's screen, threading parents stops buying anything."""
        host = QtWidgets.QWidget()
        self.addCleanup(host.deleteLater)
        parented = QtWidgets.QDialog(host)
        self.addCleanup(parented.deleteLater)
        self.assertIs(
            parented.screen(), host.screen(),
            "a parented dialog no longer inherits its parent's screen")


class TheSaveDialogIsTheOneSaveEngine(unittest.TestCase):
    """ROADMAP R56: every section saves through ONE dialog - Name, Category, Tags. The Name row is always built; a multi-selection GREYS it rather than dropping it, as D02 already does."""

    def _dialog(self, **kwargs):
        from amaze.dialogs import save_dialog
        dialog = save_dialog.SaveDialog(["Metal"], "Metal", **kwargs)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_the_name_row_is_built_when_no_name_is_given(self):
        dialog = self._dialog()
        self.assertIsNotNone(
            dialog.line_name,
            "the dialog dropped its Name row, so this section saves "
            "through a different form than its siblings")
        self.assertEqual("", dialog.line_name.text())
        self.assertTrue(dialog.line_name.isEnabled())

    def test_the_name_row_is_prefilled_when_one_is_given(self):
        self.assertEqual("rocks1", self._dialog(name="rocks1").line_name.text())

    def test_a_multi_selection_greys_the_name_row_instead(self):
        dialog = self._dialog(name="", name_enabled=False)
        self.assertIsNotNone(
            dialog.line_name,
            "the greyed form dropped the row, so the dialog changes "
            "SHAPE between one material and several")
        self.assertFalse(
            dialog.line_name.isEnabled(),
            "the Name field is live for a multi-selection, where one "
            "name cannot serve several assets")

    def test_a_greyed_name_is_never_harvested(self):
        dialog = self._dialog(name="", name_enabled=False)
        dialog.line_name.setText("typed anyway")
        dialog._on_accept()
        self.assertEqual(
            "", dialog.name,
            "a disabled field's text reached the save, which would "
            "rename every material of a multi-selection to one string")

    def test_a_live_name_IS_harvested(self):
        """The accept path: a harvest that answered "" always would leave every single save named after its node whatever the user typed."""
        dialog = self._dialog(name="rocks1")
        dialog.line_name.setText("renamed")
        dialog._on_accept()
        self.assertEqual("renamed", dialog.name)

    def test_a_new_category_can_be_typed_in_any_section(self):
        self.assertTrue(
            self._dialog().combo_cats.isEditable(),
            "the category cannot be typed into, so a section that used "
            "to offer a new category no longer does")

    def test_the_title_is_the_house_one_unless_a_caller_says_otherwise(self):
        from amaze import branding
        self.assertEqual("Save to " + branding.APP_NAME,
                         self._dialog().windowTitle())
        self.assertEqual("Save Gradient",
                         self._dialog(title="Save Gradient").windowTitle())


class TheSaveFamilyIsTheDrawnWidth(unittest.TestCase):
    """The save dialogs are ONE drawn width, and the measurement is taken AFTER `show()` - `SetFixedSize` re-applies the layout's own hint on every activation, so a width that is right at construction can still be wrong on screen. ▸r/fixed-size-constraint"""

    def _shown(self, dialog):
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        QtWidgets.QApplication.processEvents()
        self.addCleanup(dialog.hide)
        return dialog

    def _dialogs(self):
        """D09 is THE save frame: every section rides it, so the greyed and the titled forms are the same three rows. ▸p/one-design-document"""
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
        """Constructing each one, which no test did before - `CodeDialog` referenced a design constant that had been renamed and nothing noticed, because every dialog test until now read source or signatures instead of building the widget."""
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
            "the code dialog opens narrower than its drawn floor")
        self.assertLess(    # the drawn 2x2: the editor spans the FULL width under both halves, so it starts left of the indented Name field
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

    def test_only_the_drawn_three_wear_a_header_band(self):
        """D01, D02 and D11 carry the drawn strip; the save family and Preferences do not, and a band appearing on one of those is the misreading that put it there in the first place. ▸p/one-design-document"""
        from amaze.dialogs import (code_dialog, gradient_dialog,
                                   icon_dialog, prefs_dialog, save_dialog)
        wants = (
            ("D02 Customize", lambda: icon_dialog.IconDialog(
                None, 0.0, None, tile_name="rocks1"), True),
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
        self.assertFalse(
            hasattr(prefs_dialog.PrefsDialog, "HEADER_BAND")
            and prefs_dialog.PrefsDialog.HEADER_BAND,
            "Preferences declares a header band, which no D04-D08 "
            "frame draws")

    def test_the_code_dialog_band_names_the_SNIPPET(self):
        """Its window title is a verb, so the band takes the name field - and says `Untitled` while there is none."""
        from amaze import amazetheme
        from amaze.dialogs import code_dialog
        for tag, name, expect in (
                ("new", "", amazetheme.BAND_UNTITLED),
                ("named", "helper", "helper")):
            with self.subTest(snippet=tag):
                dialog = self._shown(
                    code_dialog.CodeDialog(["Metal"], name=name))
                label = dialog.findChild(QtWidgets.QLabel,
                                         "amaze_header_band_text")
                self.assertIsNotNone(label, "the band carries no text")
                self.assertEqual(expect, label.text())

    def test_the_family_renders_ONE_width_whatever_that_width_is(self):
        """The structural property, and it is stronger than the value: four dialogs reading ONE constant must AGREE, so a broken mechanism shows up as one wrong number rather than four different ones. Four different widths is proof the constant never reached them. ▸p/shared-means-it-fails-together"""
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
        from amaze import amazetheme
        from amaze.helpers import theme
        want = theme.ui_px(amazetheme.SAVE_FIELD_WIDTH)
        for label, dialog in self._dialogs():
            with self.subTest(dialog=label):
                shown = self._shown(dialog)
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

    def test_the_width_survives_a_second_layout_pass(self):
        """A `show()` is not the last activation a dialog sees - a re-show, a font change or a re-polish activates the layout again."""
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
            "the width held on show and then collapsed to %d on the next "
            "layout pass" % dialog.width())


if __name__ == "__main__":
    unittest.main()
