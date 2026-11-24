"""Engine guards left from the panel tests: a location's comments, its siblings, a stale badge."""

import os
import shutil
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

from amaze.core import library_db, locations, notes, tile_icons  # noqa: E402
from amaze.prefs import prefs as prefs_mod  # noqa: E402
from amaze.tests import test_support  # noqa: E402


def _location_prefs(case, names):
    """Only the attributes a location record reads; a real `Prefs` looks up the install."""
    prefs = prefs_mod.Prefs.__new__(prefs_mod.Prefs)
    prefs.save = lambda: None
    prefs._directory = tempfile.mkdtemp(prefix="amaze_locations_")
    prefs._library_user = test_support.FIXTURE_USER
    prefs.data = {}
    prefs._file_folders = []
    prefs._file_favorites = []
    prefs._file_location_records = {}
    prefs._users_blocks = {}
    locations.forget()
    case.addCleanup(shutil.rmtree, prefs._directory, True)
    case.addCleanup(library_db.release)
    case.addCleanup(locations.forget)
    for path, name in sorted(names.items()):
        case.assertTrue(locations.set_record(prefs, path, {"registered": True, "name": name}),
                        "premise: the location %s was not written" % path)
    return prefs


class ALocationChangeKeepsItsFilesData(unittest.TestCase):
    """A relocate carries the comments and icons keyed on its path; a removal spares a sibling."""

    def test_a_relocate_keeps_the_comments_and_the_tile_icons_too(self):
        prefs = _location_prefs(self, {"/old/": "Plates"})
        key = locations.file_ident(prefs, "/old/shot.exr")
        self.assertTrue(key.startswith(locations.LOC_PREFIX), "premise: /old/ owns no file")
        self.assertTrue(notes.set_note(
            prefs, notes.note_key("file", key),
            [{"t": "text", "text": "check the gamma"}]))
        self.assertTrue(tile_icons.set_override(
            prefs, key, {"name": "box", "bg": "#ef8878"}, locations.FILES))
        asset_key = notes.note_key("material", "/old/thing")    # an asset id that looks like a path
        self.assertTrue(notes.set_note(
            prefs, asset_key, [{"t": "text", "text": "not a path"}]))

        self.assertTrue(locations.relocate_record(prefs, "/old/", "/new/"))
        moved = locations.file_ident(prefs, "/new/shot.exr")
        self.assertTrue(notes.has_note(prefs, notes.note_key("file", moved)),
                        "the comment stayed on the old path")
        self.assertEqual("", locations.file_ident(prefs, "/old/shot.exr").partition(
            locations.LOC_PREFIX)[1], "the old path still names a location")
        self.assertEqual("box", tile_icons.override_for(prefs, moved, locations.FILES).get("name"),
                         "the tile icon stayed on the old path")
        self.assertTrue(notes.has_note(prefs, asset_key),
                        "an asset key that merely LOOKS like a path was rewritten by a folder move")

    def test_removing_a_location_keeps_a_sibling(self):
        prefs = _location_prefs(self, {"/a/tex/": "Bokeh", "/a/textures/": "two"})
        locations.retire_prefix(prefs, "/a/tex/")
        self.assertEqual({}, locations.record(prefs, "/a/tex/"), "the location stayed")
        self.assertEqual("two", locations.record(prefs, "/a/textures/").get("name"),
                         "a sibling whose name merely starts the same was retired too")


class AStaleVersionsBadgeOpensNothing(unittest.TestCase):
    """An index that maps to no row is no material: row -1 indexes the LAST asset."""

    def test_an_index_with_no_row_opens_no_versions_window(self):
        from amaze.dialogs import versions_dialog
        panel = test_support.fixture_panel(self)
        model, opened = panel.pane.material_model, []
        self.assertTrue(model.assets, "premise: the fixture library holds materials")

        def dialog(name, *_args, **_kwargs):
            opened.append(name)
            return mock.Mock(exec=lambda: QtWidgets.QDialog.DialogCode.Rejected)

        with mock.patch.object(versions_dialog, "VersionsDialog", dialog), \
                mock.patch.object(model, "version_list", lambda row: (["v1", "v2"], "v1")):
            panel.pane.assets.open_versions(QtCore.QModelIndex(), panel.pane.material_sorted_model,
                                            model)
        self.assertEqual([], opened, "a stale badge opened another material's versions")


if __name__ == "__main__":
    unittest.main()
