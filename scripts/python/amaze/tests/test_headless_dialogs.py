"""The panel, the thumbnail renderer and the drag engine reach the host's dialogs only through a guard, so a refusal raised with no screen present stays a refusal. ▸r/status-bar"""

import ast
import os
import tempfile
import types
import unittest
from unittest import mock

from PySide6 import QtWidgets

import hou

from amaze.core import dragengine, material
from amaze.render import nodes, thumbs
from amaze.utils import rc_calls
from amaze.tests import test_support

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


if __name__ == "__main__":
    unittest.main()
