"""File section: one test per requirement in docs/requirements/file-section.md."""

import os
import shutil
import time
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from amaze import messages  # noqa: E402
from amaze.core import category, file_library, folders, locations, notes, users  # noqa: E402
from amaze.helpers import hostos  # noqa: E402
from amaze.prefs import prefs as prefs_mod  # noqa: E402
from amaze.tests import test_support  # noqa: E402

try:    # without Houdini the tests that need it skip
    import hou
    from amaze.actions import files as files_actions
    from amaze.core import debug, scene_captures
    from amaze.pane import drop_placement, files as pane_files, loading
    from amaze.sections import file as file_section
except ImportError:
    hou = None

CUBE = os.path.join(test_support.FILES_FIXTURE_DIR, "cube.bgeo")


def _tree(root: str) -> dict:
    """Every folder and file under `root`, a file with its bytes and its modified time."""
    found = {}
    for here, dirs, files in os.walk(root):
        for name in dirs:
            found[os.path.relpath(os.path.join(here, name), root) + "/"] = None
        for name in files:
            path = os.path.join(here, name)
            with open(path, "rb") as handle:
                found[os.path.relpath(path, root)] = (handle.read(), os.stat(path).st_mtime_ns)
    return found


def _counts(model, timeout=10.0) -> list:
    """Every sidebar row's count, once no walk is queued or running."""
    deadline = time.monotonic() + timeout
    while True:
        counts = [model.index(row, 0).data(category.SIDEBAR_COUNT_ROLE) for row in range(model.rowCount())]
        if not getattr(model, "_walking", None) and None not in counts:
            return counts
        if time.monotonic() > deadline:
            raise AssertionError("the counts never landed: %s" % counts)
        _app.processEvents()
        time.sleep(0.002)


class _Folders(unittest.TestCase):
    """The user's folders `a`, `b` and `c` under one scratch root, real preferences over a library."""

    def setUp(self):
        self.root = test_support.scratch_dir("amaze_fi_")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.a, self.b, self.c = (os.path.join(self.root, name) for name in "abc")
        for relative, text in (("a/top.png", "png"), ("a/notes.txt", "notes"), ("a/shot.hip", "hip"),
                               ("a/.hidden", "hidden"), ("a/sub/buried.txt", "buried"),
                               ("b/plate.exr", "exr"), ("c/", "")):
            test_support.put(self.root, relative, text) if text else os.makedirs(self.at(relative))
        shutil.copy(CUBE, self.a)
        self.prefs = test_support.fixture_prefs(self)

    def at(self, *parts) -> str:
        return os.path.join(self.root, *parts)

    def key(self, path: str) -> str:
        return hostos.canonical_path_key(path).rstrip("/") + "/"


class TheUsersFilesAreSafeTest(_Folders):

    def test_fi01_browsing_and_every_location_change_leave_the_users_files_as_they_were(self):
        before = _tree(self.root)
        sidebar, grid = file_library.FileFolders(self.prefs), file_library.FileFiles(self.prefs)
        for path in (self.a, self.b):
            self.assertTrue(sidebar.add_folder(self.key(path)))
        grid.set_folder(self.a)
        grid.set_all_folders()
        self.assertEqual(5, _counts(sidebar)[0], "premise: the locations were not counted")
        self.prefs.set_file_folder_name(self.key(self.a), "Shots")
        sidebar.sort_folders()
        sidebar.commit_order()
        self.assertGreaterEqual(sidebar.relocate_folder(sidebar.row_of(self.key(self.b)), self.c), 0)
        self.assertTrue(sidebar.remove_folder(sidebar.row_of(self.key(self.a))))
        self.assertEqual(before, _tree(self.root))

    @unittest.skipUnless(hou, "Houdini is not loaded")
    def test_fi02_new_folder_and_save_scene_never_write_over_anything(self):
        scene = "shot" + scene_captures.scene_extension()
        test_support.put(self.a, scene, "a scene of the user's")
        before, path = _tree(self.root), hou.hipFile.path()
        taken = messages.NEW_FOLDER_TAKEN % ("sub", self.a)
        self.assertEqual(taken, file_library.make_folder(self.a, "sub"))
        self.assertEqual(messages.SAVE_SCENE_TAKEN % (scene, self.a), files_actions.save_scene_as(self.a, scene))
        self.assertEqual(messages.SAVE_SCENE_TAKEN % (scene, self.a), files_actions.save_scene_as(self.a, "shot"))
        for name in ("x/y", "x" + os.sep + "y"):
            self.assertEqual(messages.NEW_NAME_HAS_A_SLASH % name, file_library.make_folder(self.a, name))
            self.assertEqual(messages.NEW_NAME_HAS_A_SLASH % name, files_actions.save_scene_as(self.a, name))
        with mock.patch.object(os.path, "lexists", return_value=False):    # taken a moment ago
            self.assertEqual(taken, file_library.make_folder(self.a, "sub"))
            self.assertIn(scene, files_actions.save_scene_as(self.a, "shot"))
        self.assertEqual((before, path), (_tree(self.root), hou.hipFile.path()))


@unittest.skipUnless(hou, "Houdini is not loaded")
class TheOpenSceneIsSafeTest(_Folders):

    def setUp(self):
        super().setUp()
        self.addCleanup(hou.hipFile.clear, suppress_save_prompt=True)
        self.node = hou.node("/obj").createNode("geo", "fi_scene")

    def test_fi10_opening_a_scene_asks_houdinis_own_save_prompt_first(self):
        pane = types.SimpleNamespace(files=types.SimpleNamespace(hip_path_for=lambda index: self.at("a", "shot.hip")))
        with mock.patch.object(hou.hipFile, "load") as load:
            file_section.FileSection(pane).open_hip_scene(object())
        self.assertEqual(False, load.call_args.kwargs.get("suppress_save_prompt"))

    def test_fi11_save_scene_saves_the_scene_whole_as_the_open_one_and_a_failure_says_why(self):
        extension = scene_captures.scene_extension()
        for typed, saved in (("take1", "take1" + extension), ("take2" + extension, "take2" + extension),
                             ("take3.hip", "take3" + extension)):
            with self.subTest(typed):
                self.assertEqual("", files_actions.save_scene_as(self.b, typed))
                path = os.path.join(self.b, saved)
                self.assertEqual(self.key(path).rstrip("/"), hostos.canonical_path_key(hou.hipFile.path()))
                self.assertIn(self.node.path(), [n.path() for n in hou.hipFile.collisionNodesIfMerged(path)])
        before, listed = hou.hipFile.path(), sorted(os.listdir(self.b))
        blocked = self.at("b", "plate.exr")    # a file, so no folder can be made under it
        self.assertTrue(files_actions.save_scene_as(blocked, "take4").startswith(
            messages.SAVE_SCENE_FAILED.split("%s")[0]))
        with mock.patch.object(hou.hipFile, "save", side_effect=hou.OperationFailed("the disk is full")):
            self.assertIn("the disk is full", files_actions.save_scene_as(self.b, "take5"))
        self.assertEqual((before, listed), (hou.hipFile.path(), sorted(os.listdir(self.b))))


class LocationsTest(_Folders):

    def test_fi20_a_location_lists_its_own_files_but_hidden_ones_by_their_kind(self):
        grid = file_library.FileFiles(self.prefs)
        grid.set_folder(self.a)
        listed = {grid.index(row, 0).data(): grid.index(row, 0).data(grid.KindRole)
                  for row in range(grid.rowCount())}
        self.assertEqual({"cube.bgeo": locations.KIND_GEO, "notes.txt": locations.KIND_OTHER,
                          "shot.hip": locations.KIND_HIP, "top.png": locations.KIND_IMAGE}, listed)

    def test_fi21_one_id_for_every_user_and_each_users_own_name_colour_and_place(self):
        second = prefs_mod.Prefs()
        second.dir, second.path = self.prefs.dir, test_support.scratch_dir("amaze_fi_second_")
        self.addCleanup(shutil.rmtree, second.path, True)
        second.library_user = users.create(self.prefs, "Second")
        a, b = self.key(self.a), self.key(self.b)
        for prefs, order in ((self.prefs, (a, b)), (second, (b, a))):
            sidebar = file_library.FileFolders(prefs)
            for path in order:
                self.assertTrue(sidebar.add_folder(path))
        self.assertEqual(locations.location_id(self.prefs, a), locations.location_id(second, a))
        self.prefs.set_file_folder_name(a, "Shots")
        self.prefs.set_file_folder_color(a, "#123456")
        self.assertEqual(([a, b], "Shots", "#123456"), (self.prefs.file_folders, self.prefs.file_folder_names.get(
            a), self.prefs.file_folder_colors.get(a)))
        self.assertEqual(([b, a], {}, {}), (second.file_folders, second.file_folder_names,
                                            second.file_folder_colors))
        ident = locations.file_ident(self.prefs, self.at("a", "notes.txt"))
        self.assertTrue(notes.set_note(self.prefs, notes.note_key("file", ident),
                                       [{"t": "text", "text": "the first user's"}]))
        self.assertTrue(locations.register(second, self.root))    # a location around it
        self.assertEqual(ident, locations.file_ident(second, self.at("a", "notes.txt")))
        self.assertTrue(notes.has_note(second, notes.note_key("file", ident)))

    def test_fi22_locate_keeps_the_locations_id_name_and_data_and_refuses_a_location(self):
        sidebar = file_library.FileFolders(self.prefs)
        for path in (self.a, self.b):
            sidebar.add_folder(self.key(path))
        a = self.key(self.a)
        self.prefs.set_file_folder_name(a, "Shots")
        self.prefs.add_file_favorite(a + "notes.txt")
        lid = locations.location_id(self.prefs, a)
        self.assertEqual(folders.ALREADY_A_LOCATION, sidebar.relocate_folder(sidebar.row_of(a), self.b))
        self.assertEqual(1, sidebar.relocate_folder(sidebar.row_of(a), self.c))
        c = self.key(self.c)
        self.assertEqual((lid, "Shots"), (locations.location_id(self.prefs, c), self.prefs.file_folder_names.get(c)))
        self.assertIn(c + "notes.txt", self.prefs.file_favorites)

    @unittest.skipUnless(hou, "Houdini is not loaded")
    def test_fi23_removing_a_location_asks_first(self):
        sidebar = file_library.FileFolders(self.prefs)
        sidebar.add_folder(self.key(self.a))
        row = sidebar.row_of(self.key(self.a))
        pane = types.SimpleNamespace(file_folders_model=sidebar, sidebar=types.SimpleNamespace(
            rows=lambda: [sidebar.index(row, 0)]))
        asked = []
        for answer, removed in ((1, []), (0, [self.key(self.a)])):
            ui = types.SimpleNamespace(displayMessage=lambda text, **k: asked.append(text) or answer)
            with mock.patch.object(hou, "ui", ui, create=True):
                self.assertEqual(removed, pane_files.Files(pane).remove_locations())
        self.assertEqual([messages.REMOVE_LOCATION_CONFIRM % '"a"'] * 2, asked)
        self.assertNotIn(self.key(self.a), self.prefs.file_folders)


@unittest.skipUnless(hou, "Houdini is not loaded")
class IntoTheSceneTest(_Folders):

    def setUp(self):
        super().setUp()
        self.geo = hou.node("/obj").createNode("geo", "fi_geo")
        self.addCleanup(test_support.drop_node, self.geo)
        self.addCleanup(hou.undos.clear)
        self.pane = types.SimpleNamespace(prefs=types.SimpleNamespace(path_style="home"),
                                          file_files_model=file_library.FileFiles)
        self.pane.drop_placement = drop_placement.DropPlacement(self.pane)

    @staticmethod
    def rows(*paths) -> list:
        return [types.SimpleNamespace(data=lambda role, path=path: path) for path in paths]

    def test_fi24_load_asset_imports_the_geometry_into_the_network_shown_as_one_undo_step(self):
        loads = loading.Loading(self.pane)
        hou.undos.clear()
        with mock.patch.object(loads, "_active_network_pwd", return_value=self.geo):
            loads.import_geo_assets(self.rows(CUBE, self.at("a", "cube.bgeo")))
        self.assertEqual(["cube", "cube1"], sorted(node.name() for node in self.geo.children()))
        self.assertEqual(("Amaze Import Geometry",), hou.undos.undoLabels())
        hou.undos.performUndo()
        self.assertEqual((), self.geo.children())

    def test_fi25_copy_path_spells_each_path_as_write_paths_as_one_per_line(self):
        home = hou.text.expandString("$HOME")
        for style, first in (("home", "$HOME/plate.exr"), ("absolute", self.key(home) + "plate.exr")):
            self.pane.prefs.path_style = style
            pane_files.Files(self.pane).copy_paths(self.rows(os.path.join(home, "plate.exr"), self.b))
            self.assertEqual(first + "\n" + hostos.canonical_path_key(self.b),
                             QtGui.QGuiApplication.clipboard().text())

    def test_fi26_the_hip_row_follows_save_open_and_new(self):
        self.addCleanup(hou.hipFile.clear, suppress_save_prompt=True)
        shown = []
        watch = files_actions.watch_scene(types.SimpleNamespace(set_scene_folder=shown.append))
        self.addCleanup(files_actions.unwatch_scene, watch)
        path = os.path.join(self.c, "shot.hip")
        for step, folder in ((lambda: hou.hipFile.save(path, save_to_recent_files=False), self.c),
                             (lambda: hou.hipFile.clear(suppress_save_prompt=True), ""),
                             (lambda: hou.hipFile.load(path, suppress_save_prompt=True), self.c)):
            step()
            self.assertEqual(self.key(folder) if folder else "", shown[-1])

    def test_fi27_new_folder_and_save_scene_act_on_the_folder_shown_and_are_off_on_all(self):
        grid = file_library.FileFiles(self.prefs)
        pane = types.SimpleNamespace(file_files_model=grid,
                                     ui=types.SimpleNamespace(ask_name=lambda title, default, then: then("New")))
        section = file_section.FileSection(pane)
        grid.set_folder(self.c)
        self.assertTrue(section.menu_new_enabled([], None))
        section.menu_new_folder([], None)
        self.assertTrue(os.path.isdir(os.path.join(self.c, "New")))
        grid.set_all_folders()
        self.assertFalse(section.menu_new_enabled([], None))
        for licence, extension in (("Commercial", ".hip"), ("Indie", ".hiplc"), ("Apprentice", ".hipnc")):
            with mock.patch.object(hou, "licenseCategory", return_value=types.SimpleNamespace(name=lambda: licence)):
                self.assertEqual(extension, scene_captures.scene_extension())


if __name__ == "__main__":
    unittest.main()
