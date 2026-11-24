"""Format 4: an asset is `<section>/<id>.mat|.json|.png`; one module alone names format 3."""
import hashlib
import json
import os
import shutil
import sys
import types
import unittest
from unittest import mock

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # BEFORE the app exists ▸p/first-app-picks-the-platform
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from amaze import messages  # noqa: E402
from amaze.core import asset_record, guard, library_conversion, library_db, library_files  # noqa: E402
from amaze.core import library_policy, material, versions  # noqa: E402
from amaze.prefs import prefs as prefs_mod  # noqa: E402
from amaze.tests import test_support  # noqa: E402

MATERIALS = library_files.MATERIALS
ROW = {"id": "", "name": "Brick", "categories": ["Walls"], "tags": ["red"],
       "renderer": "Redshift", "date": "2026-01-01 00:00:00", "usd": 1}
OLD_BUILDER = {"format": 1, "type": "rs_usd_material_builder",
               "dialog_script": "{ name parms }", "values": {"tabmenumask": {"str": "rs"}}}
INTERFACE = "node = hou_parent.createNode('rs_usd_material_builder', 'x')\n"
PACKAGE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(PACKAGE)))


def write(path: str, data) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if isinstance(data, bytes):
        with open(path, "wb") as handle:
            handle.write(data)
        return path
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(data if isinstance(data, str) else json.dumps(data))
    return path


def read_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def listing(folder: str) -> dict:
    """{relative path: (size, sha1)} of every file under `folder`."""
    found = {}
    for here, _dirs, names in os.walk(folder):
        for name in names:
            path = os.path.join(here, name)
            data = read_bytes(path)
            found[os.path.relpath(path, folder)] = (len(data), hashlib.sha1(data).hexdigest())
    return found


def trashed(directory: str) -> int:
    """How many files the library trash holds."""
    return guard.Guard(directory).trash_held()["files"]


class _Library(unittest.TestCase):
    """A fixture copy, preferences pointing at it, and format 3 files written into it."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.dir = self.prefs.dir
        self.old = os.path.join(self.dir, "mat")
        self.materials = material.section_folder(self.dir, MATERIALS)

    def at(self, *parts) -> str:
        return os.path.join(self.dir, *parts)

    def database(self, filename: str, ids, **names) -> None:
        """`filename` holding a row per id, added to what it holds already."""
        path = self.at(filename)
        document = {"format": 3, "categories": ["_All", "Walls"], "tags": [], "assets": []}
        if os.path.exists(path):
            with open(path, encoding="utf-8-sig") as handle:
                document = json.load(handle)
        document["assets"] += [dict(ROW, id=one, name=names.get(one, "Brick " + one))
                               for one in ids]
        write(path, document)

    def old_asset(self, asset_id: str, folder=None, builder=True, stamp=True) -> list:
        """A format 3 asset: `.mat`, `.interface`, and optionally its sidecar and its stamp."""
        folder = folder or self.old
        made = [write(os.path.join(folder, asset_id + ".mat"), "nodes of %s\n" % asset_id),
                write(os.path.join(folder, asset_id + ".interface"), INTERFACE)]
        if builder:
            made.append(write(os.path.join(folder, asset_id + ".builder.json"), OLD_BUILDER))
        if stamp:
            made.append(write(os.path.join(folder, asset_id + ".stamp.json"),
                              dict(ROW, id=asset_id, name="Stamped " + asset_id)))
        return made

    def old_pictures(self, asset_id: str) -> list:
        return [write(self.at("img", asset_id + ".png"), b"render " + asset_id.encode()),
                write(self.at("captures", asset_id + ".png"), b"capture " + asset_id.encode()),
                write(self.at("img", asset_id + "_icon.png"), b"icon " + asset_id.encode())]

    def metadata(self, asset_id: str, **changed) -> None:
        asset_record.write_section(asset_record.path_for(self.prefs, asset_id, MATERIALS),
                                   asset_record.METADATA, dict(ROW, id=asset_id, **changed))


class _OldLibrary(_Library):
    """An older library built from scratch: its root files, `mat/`, `img/`, `captures/`."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.dir = test_support.scratch_dir("amaze_old_library_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.prefs = prefs_mod.Prefs()
        self.prefs.dir = self.dir
        self.prefs.path = test_support.scratch_dir("amaze_old_library_prefs_")
        self.addCleanup(shutil.rmtree, self.prefs.path, True)
        self.prefs.library_user = test_support.FIXTURE_USER
        self.old = os.path.join(self.dir, library_conversion.OLD_FOLDER)
        self.materials = material.section_folder(self.dir, MATERIALS)
        write(self.at(library_conversion.OLD_POLICY),
              {"library_version": library_policy.LIBRARY_VERSION - 1})
        os.makedirs(self.old)


class NothingChangesUnlessItRunsTest(_OldLibrary):
    """Opened headless or saved to: an older library is byte for byte what it was."""

    def lay_out(self):
        self.database("library.json", ["MAT1"])
        self.database("cops.json", ["NODE1"])
        self.old_asset("MAT1")
        self.old_asset("NODE1")
        self.old_pictures("MAT1")
        return listing(self.dir)

    def test_opening_it_changes_nothing_and_makes_no_library_in_it(self):
        from amaze.actions import library as library_actions
        before = self.lay_out()
        self.assertFalse(library_actions.index_present(self.dir), "an older library was read as a current one")
        self.assertTrue(library_actions.folder_not_empty_without_library(self.dir),
                        "a folder that is not empty would be given a new library")
        with mock.patch.object(library_actions.debug, "alert") as said:
            library_actions.prepare(self.prefs)
        self.assertEqual(messages.LIBRARY_FOLDER_NOT_EMPTY, said.call_args[0][0])
        self.assertEqual(before, listing(self.dir), "opening it changed the folder")

    def test_a_save_writes_nothing_into_it(self):
        from amaze.core import library_settings
        write(self.at("users.json"), {"users": {test_support.FIXTURE_USER: {"name": "Anna"}}})
        self.database("library.json", ["MAT1"])
        self.old_asset("MAT1")
        before = listing(self.dir)
        self.assertFalse(library_settings.takes_writes(self.prefs))
        self.prefs.rendersize = 512
        self.prefs.save()
        self.assertEqual(before, listing(self.dir), "a save wrote into an older library")

    def test_the_open_flow_names_no_conversion(self):
        import inspect
        from amaze.actions import library as library_actions
        from amaze.pane import library as pane_library
        for where in (pane_library.Library.start, pane_library.Library.open_library,
                      pane_library.Library._open_at_start,
                      pane_library.Library.ensure_library_user, library_actions):
            self.assertNotIn("library_conversion", inspect.getsource(where), str(where))


class OnlyTheConverterNamesFormat3Test(unittest.TestCase):
    """Every module but the converter reads 2.0 only: no old file, copy, key or module named."""

    NAMES = (".interface", ".builder.json", ".stamp.json", "_icon.png", '"mat/"',
             "LEGACY_ASSET_FOLDER",
             "library.json", "cops.json", "gradients.json", "notes.json", "icons.json",
             "favourites.json", "locations.json", "location_paths.json", "users.json",
             "prefs.json", "policy.json", "pre-adopt", "TEXTURE_UPDATE_BACKUP",
             ".bak-", "bak-first", "bak-before-restore", "history_root", "record_history",
             "snapshot_before_write", "seed_restore_floor", "existed_before",
             ".amaze_gradient_seed", ".amaze_code_starter", ".assetlib_", "material_favorites",
             "category_colors", "SCHEMA_VERSION", "RETIRED_KEYS = (\"tags\"",
             "keyed_store", "DatabaseConnector", "library_prefs", "quarantine", "restore_lib",
             "OVERRIDES_FILE", "NOTES_FILE", "absent_but_known", "adopt_retired_text",
             "helpers import restore", "core import database", "core.database")

    def sources(self):
        for here, dirs, names in os.walk(PACKAGE):
            dirs[:] = [name for name in dirs if name not in ("tests", "__pycache__")]
            for name in names:
                path = os.path.join(here, name)
                if name.endswith(".py") and os.path.relpath(path, PACKAGE) != os.path.join(
                        "core", "library_conversion.py"):
                    yield path
        tools = os.path.join(REPO, "tools")
        for name in sorted(os.listdir(tools)):
            if name.endswith(".py"):
                yield os.path.join(tools, name)

    def test_no_other_module_names_an_old_shape(self):
        offenders = []
        checked = 0
        for path in self.sources():
            checked += 1
            with open(path, encoding="utf-8") as handle:
                for number, line in enumerate(handle, 1):
                    for name in self.NAMES:
                        if name in line:
                            offenders.append("%s:%d %s" % (os.path.relpath(path, REPO),
                                                           number, name))
        self.assertGreater(checked, 50, "premise: the package was found")
        self.assertEqual([], offenders, "format 3 named outside the converter:\n"
                         + "\n".join(offenders))

    SETTINGS_NAMES = ("texture_folders", "texture_favorites", "last_texture_folder",
                      "texture_include_subfolders", "geometry_folders", "geometry_favorites",
                      "last_geometry_folder", "geometry_include_subfolders", "hip_folders",
                      "hip_favorites", "last_hip_folder", "hip_include_subfolders",
                      "file_section_migrated", "version_author", '"asset_dir"',
                      "star_color_mode", "star_custom_color", '"file_folder_names"',
                      '"file_folder_colors"', '"file_folder_show_all"',
                      '"file_recursive_folders"', "file_include_subfolders", "last_renderer",
                      "enabled_sections_seen", "migrat", "legacy", "retired", "retire")

    def test_the_settings_code_names_no_older_layout(self):
        """`prefs/` reads and writes one settings layout: no older key, and no code to move one."""
        folder = os.path.join(PACKAGE, "prefs")
        offenders = []
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(folder, name), encoding="utf-8") as handle:
                for number, line in enumerate(handle, 1):
                    offenders += ["prefs/%s:%d %s" % (name, number, old)
                                  for old in self.SETTINGS_NAMES if old in line.lower()]
        self.assertEqual([], offenders, "an older settings layout named in prefs/:\n"
                         + "\n".join(offenders))


class OneSectionNeverClobbersTheOtherTest(_Library):
    """Two writers share `<id>.json`: each replaces its own section and keeps the other."""

    def test_a_metadata_write_keeps_the_builder(self):
        path = asset_record.path_for(self.prefs, "KEEP1", MATERIALS)
        asset_record.write_section(path, asset_record.BUILDER,
                                   {"type": "t", "interface": "", "values": {}})
        asset_record.write_section(path, asset_record.METADATA, {"name": "n"})
        self.assertEqual("t", asset_record.read(path)["builder"]["type"])

    def test_a_builder_write_keeps_the_metadata(self):
        path = asset_record.path_for(self.prefs, "KEEP2", MATERIALS)
        asset_record.write_section(path, asset_record.METADATA, {"name": "n"})
        asset_record.write_section(path, asset_record.BUILDER,
                                   {"type": "t", "interface": "", "values": {}})
        self.assertEqual({"name": "n"}, asset_record.read(path)["metadata"])

    def test_a_corrupt_file_reads_empty_and_is_never_written_over(self):
        """Neither a section write nor the save of its row replaces a file that cannot be read."""
        path = write(asset_record.path_for(self.prefs, "BAD1", MATERIALS), "{nope")
        write(os.path.join(self.materials, "BAD1.mat"), "nodes of BAD1\n")
        self.assertEqual({"metadata": {}, "builder": {}}, asset_record.read(path))
        with self.assertRaises(OSError):
            asset_record.write_section(path, asset_record.METADATA, {"name": "n"})
        held = library_db.document(self.prefs, MATERIALS)
        self.assertTrue(held.put("assets", "BAD1", dict(ROW, id="BAD1")))
        test_support.settle_stamps()
        self.assertTrue(held.get("assets", "BAD1"), "premise: the row was saved")
        self.assertEqual(b"{nope", read_bytes(path), "an unreadable record was overwritten")

    def test_the_saved_builder_is_the_json_s_alone(self):
        self.old_asset("ALONE1", self.materials)
        self.metadata("ALONE1")
        self.assertEqual({}, asset_record.saved_builder(self.prefs, "ALONE1", MATERIALS),
                         "a format 3 sidecar beside `<id>.json` was read")


class AMetadataEditMakesNoVersionTest(_Library):
    """A version archives the builder alone: a tag edit never makes the base differ from it."""

    ASSET = "139888336268658010"

    def test_a_tag_edit_keeps_the_base_archived(self):
        self.metadata(self.ASSET)
        self.assertEqual(1, versions.create_version(self.prefs, self.ASSET))
        self.metadata(self.ASSET, tags=["blue"])
        self.assertTrue(versions.keep_base(self.prefs, self.ASSET))
        self.assertEqual(1, versions.version_count(self.prefs, self.ASSET),
                         "a metadata edit was archived as a new version")
        with open(os.path.join(versions.versions_dir(self.prefs, self.ASSET),
                               self.ASSET + "_1.json"),
                  encoding="utf-8") as handle:
            self.assertNotIn("metadata", json.load(handle))

    def test_a_builder_change_does_differ(self):
        path = asset_record.path_for(self.prefs, self.ASSET, MATERIALS)
        versions.create_version(self.prefs, self.ASSET)
        asset_record.write_section(path, asset_record.BUILDER,
                                   {"type": "subnet", "interface": "", "values": {"x": {"val": 1}}})
        versions.keep_base(self.prefs, self.ASSET)
        self.assertEqual(2, versions.version_count(self.prefs, self.ASSET))

    def test_switching_back_keeps_the_metadata_and_restores_the_builder(self):
        path = asset_record.path_for(self.prefs, self.ASSET, MATERIALS)
        self.metadata(self.ASSET)
        versions.create_version(self.prefs, self.ASSET)
        asset_record.write_section(path, asset_record.BUILDER,
                                   {"type": "other", "interface": "", "values": {}})
        versions.create_version(self.prefs, self.ASSET)
        self.assertTrue(versions.switch_active(self.prefs, self.ASSET, 1))
        self.assertEqual("subnet", asset_record.read(path)["builder"]["type"])
        self.assertEqual("Brick", asset_record.read(path)["metadata"]["name"])

    def test_a_version_archives_only_the_new_kinds(self):
        self.assertEqual({"mat": ".mat", "json": ".json", "thumbnail": ".png"},
                         dict(versions.SOURCE_KINDS))


class OnePicturePerAssetTest(_Library):
    """`<section>/<id>.png` is the asset's picture, render or capture; a choice moves no file."""

    ASSET = "139888336268658010"

    def model(self):
        from amaze.core import library
        model = library.MaterialLibrary(self.prefs)
        return model, model.find_asset_row_by_id(self.ASSET)

    def trashed(self) -> int:
        return trashed(self.dir)

    def test_a_capture_replaces_the_render_in_place_and_nothing_is_trashed(self):
        from amaze.core import tile_icons
        model, row = self.model()
        render = tile_icons.thumbnail_path(self.prefs, self.ASSET, MATERIALS)
        self.assertEqual(render, model.capture_path(row), "a capture is written somewhere else")
        before = self.trashed()
        write(model.capture_path(row), "captured")
        for face in ("generic", "image", "generic", "image"):    # both directions, twice
            self.assertTrue(model.set_tile_icon(row, {"face": face}))
        with open(render, encoding="utf-8") as handle:
            self.assertEqual("captured", handle.read())
        self.assertEqual(before, self.trashed(), "a face switch moved a picture to the trash")

    def test_a_custom_icon_writes_no_library_file(self):
        from amaze.core import tile_icons
        model, row = self.model()
        before = sorted(os.path.join(here, name) for here, _dirs, names in os.walk(self.dir)
                        for name in names if name.endswith(".png"))
        name = tile_icons.icon_names()[0]
        self.assertTrue(model.set_tile_icon(row, {"name": name, "bg": "#e0523a", "ink": "dark"}))
        after = sorted(os.path.join(here, name) for here, _dirs, names in os.walk(self.dir)
                       for name in names if name.endswith(".png"))
        self.assertEqual(before, after, "a custom icon wrote a file into the library")
        self.assertIsNotNone(model.shown_picture(row)[0], "no icon was composed")


class AFreshLibraryTest(unittest.TestCase):
    """A new library is created with a folder per asset section and no `mat/`."""

    def test_the_section_folders_are_made(self):
        from amaze.actions import library as library_actions
        folder = test_support.scratch_dir("amaze_fresh_sections_")
        self.addCleanup(shutil.rmtree, folder, True)
        library_actions.ensure_library_dirs(types.SimpleNamespace(dir=folder))
        self.assertEqual(["materials", "nodes"], sorted(os.listdir(folder)))


if __name__ == "__main__":
    unittest.main()
