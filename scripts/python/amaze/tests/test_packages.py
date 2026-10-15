"""The `.amazepkg` format: export collects an asset's REAL file family plus its note page, plain files ride with their kind, the zip lands guarded and whole, and the reader refuses a format newer than it speaks."""

import json
import os
import sys
import tempfile
import time
import unittest
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.tests import test_support  # noqa: E402


def _bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def _out_path(testcase, name="export.amazepkg"):
    """A destination inside the suite's sandboxed tempdir - the guarded writer refuses anywhere else under the runner."""
    folder = tempfile.mkdtemp(prefix="amaze_pkg_")
    testcase.addCleanup(
        __import__("shutil").rmtree, folder, ignore_errors=True)
    return os.path.join(folder, name)


class PackageExportTest(unittest.TestCase):
    """Collect and write against the REAL fixture library - the six built materials carry genuine payload families."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _material_with_files(self):
        """The first fixture material whose payload family EXISTS on disk - the fixture's row 0 is a deliberate empty-id row that owns nothing."""
        model = self.panel.material_model
        for asset in model.assets:
            if any(os.path.exists(p)
                   for p in model.asset_files(asset.mat_id).values()):
                return asset
        self.fail("no fixture material owns payload files")

    def test_a_material_entry_carries_its_family_and_note(self):
        from amaze.core import notes, packages
        model = self.panel.material_model
        asset = self._material_with_files()
        key = notes.note_key("material", asset.mat_id)
        self.assertTrue(
            notes.set_note(self.panel.prefs, key,
                           [{"t": "text", "text": "travels"}]),
            "premise: the note page could not be written")
        self.addCleanup(notes.set_note, self.panel.prefs, key, [])
        item = packages.collect_asset(model, asset.mat_id)
        out = _out_path(self)
        wrote = packages.write_package(out, [item])
        self.assertEqual(1, wrote)
        with zipfile.ZipFile(out) as bundle:
            manifest = json.loads(bundle.read(packages.MANIFEST))
            self.assertEqual(packages.FORMAT, manifest["format"])
            entry = manifest["entries"][0]
            self.assertEqual("asset", entry["type"])
            self.assertEqual("material", entry["section"])
            self.assertEqual(asset.get_as_dict(), entry["record"],
                             "the record in the manifest is not the "
                             "asset's own")
            self.assertEqual("travels", entry["note"]["items"][0]["text"])
            self.assertTrue(entry["files"], "a built material owns real "
                                            "payload files - none packed")
            for kind, arcname in entry["files"].items():
                source = model.asset_files(asset.mat_id)[kind]
                self.assertEqual(
                    _bytes(source), bundle.read(arcname),
                    "member %r does not byte-match the library's %s"
                    % (arcname, kind))

    def test_only_existing_family_files_are_packed(self):
        from amaze.core import packages
        model = self.panel.material_model
        asset = self._material_with_files()
        item = packages.collect_asset(model, asset.mat_id)
        for kind, path in model.asset_files(asset.mat_id).items():
            if kind in packages.DERIVED:
                self.assertNotIn(kind, item["sources"],
                                 "a derived %s rode the package" % kind)
            elif os.path.exists(path):
                self.assertIn(kind, item["sources"])
            else:
                self.assertNotIn(kind, item["sources"])

    def test_a_gradient_entry_is_record_only_and_still_valid(self):
        from amaze.core import packages
        model = self.panel.gradient_model
        self.assertTrue(model.assets, "the fixture library has no gradients")
        asset = model.assets[0]
        item = packages.collect_asset(model, asset.mat_id)
        out = _out_path(self)
        self.assertEqual(1, packages.write_package(out, [item]))
        with zipfile.ZipFile(out) as bundle:
            entry = json.loads(bundle.read(packages.MANIFEST))["entries"][0]
        self.assertEqual(asset.get_as_dict(), entry["record"])
        self.assertEqual("gradient", entry["section"])

    def test_a_plain_file_rides_with_its_kind_and_bytes(self):
        from amaze.core import packages
        folder = tempfile.mkdtemp(prefix="amaze_pkg_src_")
        self.addCleanup(
            __import__("shutil").rmtree, folder, ignore_errors=True)
        source = os.path.join(folder, "rock.bgeo")
        with open(source, "wb") as handle:
            handle.write(b"geometry bytes")
        item = packages.collect_file(source, "geometry")
        out = _out_path(self)
        self.assertEqual(1, packages.write_package(out, [item]))
        with zipfile.ZipFile(out) as bundle:
            manifest = json.loads(bundle.read(packages.MANIFEST))
            entry = manifest["entries"][0]
            self.assertEqual("file", entry["type"])
            self.assertEqual("geometry", entry["kind"])
            self.assertEqual("rock.bgeo", entry["name"])
            self.assertEqual(b"geometry bytes", bundle.read(entry["arc"]))

    def test_two_files_sharing_a_basename_do_not_collide(self):
        from amaze.core import packages
        items = []
        for n in (b"one", b"two"):
            folder = tempfile.mkdtemp(prefix="amaze_pkg_dup_")
            self.addCleanup(
                __import__("shutil").rmtree, folder, ignore_errors=True)
            path = os.path.join(folder, "same.png")
            with open(path, "wb") as handle:
                handle.write(n)
            items.append(packages.collect_file(path, "image"))
        out = _out_path(self)
        self.assertEqual(2, packages.write_package(out, items))
        with zipfile.ZipFile(out) as bundle:
            arcs = [e["arc"] for e in
                    json.loads(bundle.read(packages.MANIFEST))["entries"]]
            self.assertEqual(2, len(set(arcs)),
                             "two entries share one archive member")
            self.assertEqual({b"one", b"two"},
                             {bundle.read(a) for a in arcs})

    def test_no_scratch_residue_survives_the_write(self):
        from amaze.core import packages
        model = self.panel.gradient_model
        item = packages.collect_asset(model, model.assets[0].mat_id)
        out = _out_path(self)
        packages.write_package(out, [item])
        debris = [name for name in os.listdir(os.path.dirname(out))
                  if name != os.path.basename(out)]
        self.assertEqual([], debris,
                         "the writer left scratch beside the package")


class PackageReaderTest(unittest.TestCase):
    """The reading half batch 2 builds on: the manifest comes back verbatim, and a NEWER format is refused by name."""

    def _package(self, manifest) -> str:
        folder = tempfile.mkdtemp(prefix="amaze_pkg_read_")
        self.addCleanup(
            __import__("shutil").rmtree, folder, ignore_errors=True)
        path = os.path.join(folder, "p.amazepkg")
        with zipfile.ZipFile(path, "w") as bundle:
            from amaze.core import packages
            bundle.writestr(packages.MANIFEST, json.dumps(manifest))
        return path

    def test_the_manifest_reads_back(self):
        from amaze.core import packages
        path = self._package({"format": packages.FORMAT, "entries": []})
        self.assertEqual([], packages.read_manifest(path)["entries"])

    def test_a_newer_format_is_refused_naming_both_numbers(self):
        from amaze.core import packages
        path = self._package({"format": packages.FORMAT + 1, "entries": []})
        with self.assertRaises(packages.PackageError) as caught:
            packages.read_manifest(path)
        self.assertIn(str(packages.FORMAT + 1), str(caught.exception))
        self.assertIn(str(packages.FORMAT), str(caught.exception))

    def test_a_zip_with_no_manifest_is_refused(self):
        from amaze.core import packages
        folder = tempfile.mkdtemp(prefix="amaze_pkg_bad_")
        self.addCleanup(
            __import__("shutil").rmtree, folder, ignore_errors=True)
        path = os.path.join(folder, "bad.amazepkg")
        with zipfile.ZipFile(path, "w") as bundle:
            bundle.writestr("stray.txt", "x")
        from amaze.core import packages as pkg
        with self.assertRaises(pkg.PackageError):
            pkg.read_manifest(path)

    def test_verify_names_a_missing_member(self):
        from amaze.core import packages
        path = self._package({
            "format": packages.FORMAT,
            "entries": [{"type": "file", "kind": "image",
                         "name": "a.png", "arc": "files/0_a.png"}]})
        problems = packages.verify_package(path)
        self.assertEqual(1, len(problems))
        self.assertIn("files/0_a.png", problems[0])


class ExportMenuTest(unittest.TestCase):
    """The doors: every asset section and the File grid offer Export Package, the sidebar offers Export Category, and the ACT verbs write headless with no hou.ui in the way."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def test_every_asset_section_offers_the_grid_export(self):
        from amaze.panel import sections
        for cls_ in sections.SECTION_CLASSES:
            labels = [entry.label for entry in cls_.GRID_MENU]
            self.assertIn("Export Package", labels,
                          "%s offers no package export" % cls_.key)

    def test_asset_sidebars_offer_the_category_export(self):
        from amaze.panel import sections
        for cls_ in sections.SECTION_CLASSES:
            if not issubclass(cls_, sections.AssetSection):
                continue
            labels = [entry.label for entry in cls_.SIDEBAR_MENU]
            self.assertIn("Export Category", labels,
                          "%s sidebar offers no category export" % cls_.key)

    def test_the_grid_act_door_writes_the_selection(self):
        from amaze.core import packages
        section = self.panel.sections["gradient"]
        proxy = self.panel.gradient_sorted_model
        index = proxy.index(0, 0)
        self.assertTrue(index.isValid(), "the fixture grid is empty")
        out = _out_path(self)
        wrote = section.export_package_to([index], out)
        self.assertEqual(1, wrote)
        self.assertEqual(
            1, len(packages.read_manifest(out)["entries"]))

    def test_the_category_act_door_writes_every_member(self):
        from amaze.core import packages
        section = self.panel.sections["gradient"]
        model = self.panel.gradient_model
        want = model.rowCount()
        self.assertGreater(want, 0, "the fixture library has no gradients")
        out = _out_path(self)
        wrote = section.export_category_to(None, out)
        self.assertEqual(want, wrote,
                         "the All category export missed rows")
        self.assertEqual(
            want, len(packages.read_manifest(out)["entries"]))

    def test_the_file_grid_act_door_packs_the_file(self):
        from amaze.core import packages
        import types
        from amaze.core import file_library
        folder = tempfile.mkdtemp(prefix="amaze_pkg_file_")
        self.addCleanup(
            __import__("shutil").rmtree, folder, ignore_errors=True)
        source = os.path.join(folder, "shot.exr")
        with open(source, "wb") as handle:
            handle.write(b"img")
        roles = {file_library.FileFiles.PathRole: source,
                 file_library.FileFiles.KindRole: "image"}
        index = types.SimpleNamespace(
            data=lambda role: roles.get(role), isValid=lambda: True)
        out = _out_path(self)
        wrote = self.panel.sections["file"].export_package_to([index], out)
        self.assertEqual(1, wrote)
        entry = packages.read_manifest(out)["entries"][0]
        self.assertEqual("file", entry["type"])
        self.assertEqual("image", entry["kind"])


class PackageImportTest(unittest.TestCase):
    """The import half: fresh imports mint NEW ids and land in the `Import` category, restore mode unions adopt-only by the package's ORIGINAL ids, plain files land in the library's own import folder, and a package missing a member is refused whole."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _gradient_package(self, out, fresh_note="rides along"):
        from amaze.core import notes, packages
        model = self.panel.gradient_model
        asset = model.assets[0]
        key = notes.note_key("gradient", asset.mat_id)
        self.assertTrue(notes.set_note(
            self.panel.prefs, key, [{"t": "text", "text": fresh_note}]))
        self.addCleanup(notes.set_note, self.panel.prefs, key, [])
        item = packages.collect_asset(model, asset.mat_id)
        packages.write_package(out, [item])
        return asset

    def test_a_fresh_import_mints_a_new_id_and_lands_in_Import(self):
        from amaze.core import notes, packages
        model = self.panel.gradient_model
        out = _out_path(self)
        original = self._gradient_package(out)
        before = model.rowCount()
        summary = self.panel.import_package_file(out)
        self.assertEqual(1, summary["imported"])
        self.assertEqual(before + 1, model.rowCount())
        newborn = model.assets[-1]
        self.assertNotEqual(str(original.mat_id), str(newborn.mat_id),
                            "a fresh import kept the package's id")
        cats = newborn.categories
        self.assertEqual(["Import"],
                         [cats] if isinstance(cats, str) else list(cats))
        page = notes.note_for(
            self.panel.prefs,
            notes.note_key("gradient", newborn.mat_id))
        self.assertEqual("rides along", page["items"][0]["text"],
                         "the note page did not follow the newborn id")
        self.assertIn(
            "Import", self.panel.gradient_categories_model._categories,
            "the Import category never reached the sidebar model")

    def test_a_fresh_import_twice_makes_two_copies(self):
        model = self.panel.gradient_model
        out = _out_path(self)
        self._gradient_package(out)
        before = model.rowCount()
        self.panel.import_package_file(out)
        self.panel.import_package_file(out)
        self.assertEqual(before + 2, model.rowCount(),
                         "a fresh import deduplicated - that is restore "
                         "mode's job, not this door's")

    def test_restore_mode_unions_by_the_original_id(self):
        from amaze.core import packages
        model = self.panel.gradient_model
        out = _out_path(self)
        original = self._gradient_package(out)
        before = model.rowCount()
        summary = self.panel.import_package_file(out, restore=True)
        self.assertEqual(0, summary["imported"])
        self.assertEqual(1, summary["skipped"],
                         "an id already in the library was re-imported")
        self.assertEqual(before, model.rowCount())
        with_new_id = _out_path(self, "minted.amazepkg")
        item = packages.collect_asset(model, original.mat_id)
        record = dict(item["record"], id="f" * 32)
        record.pop("curated", None)    # a USER asset: fixture palettes are born tagged since the seeder stamps, and a tagged record would union by the tag instead of the id this test pins
        item = dict(item, record=record)
        packages.write_package(with_new_id, [item])
        summary = self.panel.import_package_file(with_new_id, restore=True)
        self.assertEqual(1, summary["imported"])
        self.assertEqual("f" * 32, str(model.assets[-1].mat_id),
                         "restore minted a fresh id instead of adopting "
                         "the package's own")

    def test_a_file_entry_lands_in_the_import_location(self):
        from amaze.core import packages
        from amaze.helpers import hostos as hostos_mod
        folder = tempfile.mkdtemp(prefix="amaze_pkg_filesrc_")
        self.addCleanup(
            __import__("shutil").rmtree, folder, ignore_errors=True)
        source = os.path.join(folder, "walk.bvh")
        with open(source, "wb") as handle:
            handle.write(b"mocap")
        out = _out_path(self)
        packages.write_package(out, [packages.collect_file(source,
                                                           "other")])
        summary = self.panel.import_package_file(out)
        self.assertEqual(1, summary["files"])
        landed = os.path.join(self.panel.prefs.dir, "import", "walk.bvh")
        self.assertEqual(b"mocap", _bytes(landed))
        registered = [hostos_mod.canonical_path_key(p)
                      for p in self.panel.prefs.file_folders]
        self.assertIn(
            hostos_mod.canonical_path_key(os.path.dirname(landed)),
            registered,
            "the import folder is not a registered location, so the "
            "landed file is invisible in the File section")

    def test_a_renamed_import_location_keeps_its_name(self):
        """Only the import that registers the location names it, so a rename made since stays."""
        from amaze.core import packages
        from amaze.helpers import hostos as hostos_mod
        prefs = self.panel.prefs
        folder = hostos_mod.canonical_path_key(os.path.join(prefs.dir, "import"))
        sources = tempfile.mkdtemp(prefix="amaze_pkg_named_")
        self.addCleanup(
            __import__("shutil").rmtree, sources, ignore_errors=True)

        def import_one(name):
            path = os.path.join(sources, name)
            with open(path, "wb") as handle:
                handle.write(b"mocap")
            out = _out_path(self, name + ".amazepkg")
            packages.write_package(out, [packages.collect_file(path, "other")])
            self.assertEqual(1, self.panel.import_package_file(out)["files"])

        def name_shown():
            return {hostos_mod.canonical_path_key(path): name for path, name
                    in prefs.file_folder_names.items()}.get(folder)

        import_one("walk_named_a.bvh")
        self.assertEqual("Import", name_shown(),
                         "premise: the import location arrives named")
        prefs.set_file_folder_name(folder, "Mocap")
        self.addCleanup(prefs.set_file_folder_name, folder, "Import")
        import_one("walk_named_b.bvh")
        self.assertEqual("Mocap", name_shown(),
                         "the next import put the location's old name back")

    def test_the_import_location_arrives_as_a_sidebar_row(self):
        """Registered through the sidebar model, which tells its views and keeps its counts."""
        from amaze.core import category, packages
        from amaze.helpers import hostos as hostos_mod
        folders = self.panel.file_folders_model
        folder = hostos_mod.canonical_path_key(
            os.path.join(self.panel.prefs.dir, "import"))
        listed = [hostos_mod.canonical_path_key(p)
                  for p in self.panel.prefs.file_folders]
        if folder in listed:
            self.assertTrue(folders.remove_folder(listed.index(folder) + 1),
                            "premise: the import location stayed listed")
        sources = tempfile.mkdtemp(prefix="amaze_pkg_rows_")
        self.addCleanup(
            __import__("shutil").rmtree, sources, ignore_errors=True)

        def package_of(name):
            path = os.path.join(sources, name)
            with open(path, "wb") as handle:
                handle.write(b"mocap")
            out = _out_path(self, name + ".amazepkg")
            packages.write_package(out, [packages.collect_file(path,
                                                               "other")])
            return out

        inserted = []

        def heard(_parent, first, last):
            inserted.append((first, last))

        folders.rowsInserted.connect(heard)
        self.addCleanup(folders.rowsInserted.disconnect, heard)
        before = folders.rowCount()
        self.panel.import_package_file(package_of("walk_a.bvh"))
        self.assertEqual(
            [(before, before)], inserted,
            "the import location was registered behind the sidebar "
            "model's back, so no view heard about its row")
        row = folders.row_of(folder)
        count = folders.data(folders.index(row), category.SIDEBAR_COUNT_ROLE)
        self.panel.import_package_file(package_of("walk_b.bvh"))
        self.assertEqual(
            count + 1,
            folders.data(folders.index(row), category.SIDEBAR_COUNT_ROLE),
            "a second import landed a file in the import location and "
            "its sidebar number did not move")

    def test_a_package_missing_a_member_is_refused_whole(self):
        from amaze.core import packages
        model = self.panel.gradient_model
        out = _out_path(self)
        self._gradient_package(out)
        import zipfile as _zip
        broken = _out_path(self, "broken.amazepkg")
        with _zip.ZipFile(out) as src, _zip.ZipFile(broken, "w") as dst:
            manifest = json.loads(src.read(packages.MANIFEST))
            manifest["entries"][0]["files"]["thumbnail"] = "assets/x/y/z.png"
            dst.writestr(packages.MANIFEST, json.dumps(manifest))
        before = model.rowCount()
        with self.assertRaises(packages.PackageError):
            self.panel.import_package_file(broken)
        self.assertEqual(before, model.rowCount(),
                         "a refused package still changed the library")

    def test_an_imported_materials_family_lands_under_the_new_id(self):
        from amaze.core import packages
        model = self.panel.material_model
        asset = next(a for a in model.assets
                     if any(os.path.exists(p)
                            for p in model.asset_files(a.mat_id).values()))
        out = _out_path(self)
        packages.write_package(
            out, [packages.collect_asset(model, asset.mat_id)])
        before = model.rowCount()
        self.panel.import_package_file(out)
        self.assertEqual(before + 1, model.rowCount())
        newborn = model.assets[-1]
        sources = {k: p for k, p in
                   model.asset_files(asset.mat_id).items()
                   if k not in packages.DERIVED and os.path.exists(p)}
        for kind, source in sources.items():
            target = model.asset_files(newborn.mat_id)[kind]
            self.assertTrue(os.path.exists(target),
                            "the %s payload never landed" % kind)
            self.assertEqual(_bytes(source), _bytes(target),
                             "the %s payload does not byte-match" % kind)

    def test_an_imported_material_tile_paints(self):
        """The new row joins the model the way a saved one does: thumbnail maps and content baseline."""
        from amaze.core import packages
        model = self.panel.material_model
        asset = next(a for a in model.assets
                     if any(os.path.exists(p)
                            for p in model.asset_files(a.mat_id).values()))
        out = _out_path(self)
        packages.write_package(
            out, [packages.collect_asset(model, asset.mat_id)])
        self.panel.import_package_file(out)
        row = model.rowCount() - 1
        newborn = str(model.assets[row].mat_id)

        self.assertEqual(
            model.rowCount(), len(model._mat_paths),
            "the imported row has no thumbnail path, so every paint of its "
            "tile raises IndexError and it never shows a picture")
        model.data(model.index(row, 0),
                   QtCore.Qt.ItemDataRole.DecorationRole)    # must not raise
        self.assertIsNotNone(
            model._content_state.get(newborn),
            "no content baseline was recorded, so a later Update Existing "
            "cannot tell another machine's rewrite of these files")


class ARefusedImportIsTakenBackWhole(unittest.TestCase):
    """A refused save takes the imported row back out: the right row, with the thumbnail maps in step."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.model = self.panel.material_model

    def _package_of_a_material(self):
        from amaze.core import packages
        asset = next(a for a in self.model.assets
                     if any(os.path.exists(p) for p in
                            self.model.asset_files(a.mat_id).values()))
        out = _out_path(self)
        packages.write_package(
            out, [packages.collect_asset(self.model, asset.mat_id)])
        return out

    def _import_refused(self, out):
        from unittest import mock
        from amaze.core import database
        with mock.patch.object(database.DatabaseConnector, "save",
                               return_value=False):
            return self.panel.import_package_file(out)

    def _ids(self):
        return [str(a.mat_id) for a in self.model.assets]

    def test_the_row_leaves_the_grid(self):
        out = self._package_of_a_material()
        before = self._ids()
        self.assertEqual(1, self._import_refused(out)["refused"])
        self.assertEqual(before, self._ids(),
                         "a refused import stayed in the grid")
        self.assertEqual(self.model.rowCount(), len(self.model._mat_paths),
                         "the take-back left the thumbnail maps out of step")

    def test_a_refused_import_is_not_written_by_the_next_save(self):
        out = self._package_of_a_material()
        before = self._ids()
        self.assertEqual(1, self._import_refused(out)["refused"])

        self.assertTrue(self.model.save(), "premise: the next save failed")

        path = os.path.join(self.panel.prefs.dir, "library.json")
        with open(path, encoding="utf-8-sig") as handle:
            on_disk = [str(row.get("id")) for row in json.load(handle)["assets"]]
        self.assertEqual(sorted(before), sorted(on_disk),
                         "the refused import reached disk with the next save")

    def test_the_right_row_leaves_after_the_save_dropped_another(self):
        """The save first takes in another machine's deletion, so the new row has moved."""
        path = os.path.join(self.panel.prefs.dir, "library.json")
        self.assertTrue(self.model.save(), "premise: the first save failed")
        out = self._package_of_a_material()
        with open(path, encoding="utf-8-sig") as handle:
            document = json.load(handle)
        victim = str(document["assets"][2]["id"])
        document["assets"] = [row for row in document["assets"]
                              if str(row.get("id")) != victim]
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, indent=4)
        self.assertTrue(self.panel.category_model.save(),
                        "premise: the sidebar save was refused")
        expected = [mat_id for mat_id in self._ids() if mat_id != victim]

        self.assertEqual(1, self._import_refused(out)["refused"])

        self.assertEqual(
            expected, self._ids(),
            "the take-back aimed at the row the import was appended at, "
            "but the save had already dropped a row above it")


class AFiveAssetImportSavesOnce(unittest.TestCase):
    """Five materials out of one package reach the list in ONE save; a refused one takes all five back."""

    def setUp(self):
        from amaze.core import packages
        self.panel = test_support.fixture_panel(self)
        self.model = self.panel.material_model
        owners = [a for a in self.model.assets
                  if any(os.path.exists(p) for p in
                         self.model.asset_files(a.mat_id).values())]
        self.assertGreaterEqual(len(owners), 5, "premise: five materials")
        self.out = _out_path(self)
        packages.write_package(self.out, [
            packages.collect_asset(self.model, a.mat_id) for a in owners[:5]])

    def _import(self, refuse=False):
        from unittest import mock
        from amaze.core import database, packages
        save = database.DatabaseConnector.save
        with mock.patch.object(database.DatabaseConnector, "save",
                               autospec=True,
                               side_effect=(lambda db: False) if refuse
                               else save) as saves:
            summary = packages.import_package(
                self.panel._package_models(), self.panel.prefs, self.out)
        return summary, saves.call_count

    def test_five_materials_land_in_one_save(self):
        before = self.model.rowCount()
        summary, saves = self._import()
        self.assertEqual(5, summary["imported"], summary)
        self.assertEqual(1, saves, "five imported materials saved the list "
                                   "%d times" % saves)
        self.assertEqual(before + 5, self.model.rowCount())
        path = os.path.join(self.panel.prefs.dir, "library.json")
        with open(path, encoding="utf-8-sig") as handle:
            on_disk = {str(r.get("id")) for r in json.load(handle)["assets"]}
        self.assertTrue({str(a.mat_id) for a in self.model.assets[-5:]}
                        <= on_disk, "the imported rows never reached the file")

    def test_a_refused_save_takes_all_five_back(self):
        before = [str(a.mat_id) for a in self.model.assets]
        summary, _saves = self._import(refuse=True)
        self.assertEqual((0, 5), (summary["imported"], summary["refused"]),
                         summary)
        self.assertEqual(before, [str(a.mat_id) for a in self.model.assets],
                         "a refused import left rows in the grid")
        self.assertEqual(self.model.rowCount(), len(self.model._mat_paths))


class _Cats:
    _categories = []    # the rename helper reads the sidebar list; empty means nothing to rename

    def check_add_category(self, name):
        pass


class CuratedKeysTest(unittest.TestCase):
    """The stable identity under the defaults: every seeded row carries a `curated` tag (riding `_extra`, no schema work), and restore unions by the TAG where one exists - the same palette in two libraries has two ids but one tag."""

    def _fresh_prefs(self, marker):
        p = test_support.fixture_prefs(self)
        try:
            os.remove(os.path.join(p.dir, marker))
        except OSError:
            pass
        return p

    def test_the_gradient_seeder_stamps_curated_keys(self):
        from amaze.core import gradient_library
        p = self._fresh_prefs(".amaze_gradient_seed_v1")
        model = gradient_library.GradientLibrary(p)
        before = model.rowCount()
        model.seed_curated_palettes(_Cats())
        self.assertGreater(model.rowCount(), before,
                           "premise: the seed never ran")
        fresh = model._assets[before:]
        untagged = [a.name for a in fresh if not a._extra.get("curated")]
        self.assertEqual([], untagged[:5],
                         "seeded palettes carry no curated tag")
        sets_seen = {str(a._extra.get("curated", "")).split("/")[0]
                     for a in fresh}
        self.assertLessEqual({"wada", "klee", "albers", "itten"},
                             sets_seen)

    def test_the_code_seeder_stamps_curated_keys(self):
        from amaze.core import code_library
        p = self._fresh_prefs(".amaze_code_starter_v1")
        model = code_library.CodeLibrary(p)
        before = model.rowCount()
        model.seed_starter_snippets(_Cats())
        self.assertGreater(model.rowCount(), before,
                           "premise: the seed never ran")
        fresh = model._assets[before:]
        untagged = [a.name for a in fresh
                    if not str(a._extra.get("curated", ""))
                    .startswith("starter/")]
        self.assertEqual([], untagged[:5],
                         "seeded snippets carry no starter/ tag")

    def test_a_deleted_default_comes_back_from_the_set_package(self):
        from amaze.core import gradient_library, packages
        p = self._fresh_prefs(".amaze_gradient_seed_v1")
        model = gradient_library.GradientLibrary(p)
        model.seed_curated_palettes(_Cats())
        wada = [a for a in model._assets
                if str(a._extra.get("curated", "")).startswith("wada/")]
        self.assertGreater(len(wada), 100, "premise: the Wada set seeded")
        out = _out_path(self, "wada.amazepkg")
        packages.write_package(
            out, [packages.collect_asset(model, a.mat_id) for a in wada])
        victim = wada[3]
        gone_tag = victim._extra["curated"]
        gone_cat = victim.categories
        at = model._assets.index(victim)
        model.beginRemoveRows(QtCore.QModelIndex(), at, at)
        try:
            model._assets.pop(at)
        finally:
            model.endRemoveRows()
        self.assertTrue(model.save(), "premise: the delete never landed")
        before = model.rowCount()
        summary = packages.import_package({"gradient": model}, p, out,
                                          restore=True)
        self.assertEqual(1, summary["imported"],
                         "the deleted palette did not come back")
        self.assertEqual(len(wada) - 1, summary["skipped"],
                         "palettes still present were re-imported")
        self.assertEqual(before + 1, model.rowCount())
        returned = model._assets[-1]
        self.assertEqual(gone_tag, returned._extra.get("curated"))
        self.assertEqual(gone_cat, returned.categories,
                         "the restored palette lost its own category")

    def test_restore_unions_by_the_curated_key(self):
        from amaze.core import gradient_library, packages
        p = test_support.fixture_prefs(self)
        model = gradient_library.GradientLibrary(p)
        models = {"gradient": model}

        def _package(record_id):
            out = _out_path(self, "curated_%s.amazepkg" % record_id[0])
            record = {"id": record_id, "name": "Combination X",
                      "categories": ["Wada 3 Colors"],
                      "curated": "wada/x-999"}
            with zipfile.ZipFile(out, "w") as bundle:
                bundle.writestr(packages.MANIFEST, json.dumps({
                    "format": packages.FORMAT,
                    "entries": [{"type": "asset", "section": "gradient",
                                 "id": record_id, "record": record,
                                 "note": {}, "files": {}}]}))
            return out

        before = model.rowCount()
        first = packages.import_package(models, p, _package("a" * 32),
                                        restore=True)
        self.assertEqual(1, first["imported"],
                         "an absent curated row was not restored")
        second = packages.import_package(models, p, _package("b" * 32),
                                         restore=True)
        self.assertEqual(1, second["skipped"],
                         "the same curated tag under a DIFFERENT id was "
                         "restored again - the union keyed on the id")
        self.assertEqual(before + 1, model.rowCount())


def _canned_amaze_source(tree, bundles):
    """An AmazeSource whose two network doors are canned: `tree` rows and {url: local zip path} - counters on the class."""
    from amaze.core import matx_sources

    class Source(matx_sources.AmazeSource):
        tree_calls = 0
        open_calls = []

        def _tree(self):
            type(self).tree_calls += 1
            return list(tree)

        def _open_package(self, url):
            type(self).open_calls.append(url)
            return zipfile.ZipFile(bundles[url])

    return Source()


def _manifest_zip(testcase, entries, members=None,
                  name="pkg.amazepkg", fmt=None) -> str:
    """A local package from raw manifest entries plus optional {arcname: bytes} members; `fmt` overrides the manifest format number."""
    from amaze.core import packages
    folder = tempfile.mkdtemp(prefix="amaze_store_pkg_")
    testcase.addCleanup(
        __import__("shutil").rmtree, folder, ignore_errors=True)
    path = os.path.join(folder, name)
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr(packages.MANIFEST, json.dumps(
            {"format": packages.FORMAT if fmt is None else fmt,
             "entries": entries}))
        for arc, data in (members or {}).items():
            bundle.writestr(arc, data)
    return path


class _Served:
    """One canned HTTP answer: the bytes and their headers."""

    def __init__(self, data, headers):
        self._data, self.headers = data, headers

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _ranged_server(blob, before=None):
    """A stand-in for `matx_sources._request` serving `blob` by ranges; `before(spec)` runs first."""

    def serve(url, headers=None):
        spec = str((headers or {}).get("Range") or "")
        if before is not None:
            before(spec)
        if spec.startswith("bytes=-"):
            start = max(0, len(blob) - int(spec.split("-", 1)[1]))
            return _Served(blob[start:], {
                "Content-Range": "bytes %d-%d/%d"
                % (start, len(blob) - 1, len(blob))})
        if spec:
            lo, _, hi = spec.replace("bytes=", "").partition("-")
            return _Served(blob[int(lo):min(int(hi), len(blob) - 1) + 1], {})
        return _Served(blob, {})

    return serve


def _palette_entry(n, tag=None):
    return {"type": "asset", "section": "gradient",
            "id": "%032x" % n,
            "record": {"id": "%032x" % n, "name": "Palette %d" % n,
                       "categories": ["Wada 2 Colors"],
                       "colors": [{"hex": "#101010"}, {"hex": "#f0f0f0"}],
                       "curated": tag or "wada/t%d" % n},
            "note": {}, "files": {}}


class AmazeSourceTest(unittest.TestCase):
    """The store source, per-TILE: every entry in every package of a folder is one record, palette colours ride the record for client-side swatches, material thumbnails are named members, a NEWER-format package is refused whole, and Refresh drops every cache."""

    URL = "https://raw.githubusercontent.com/Timour/AmazePackages/main/"

    def _two_package_folder(self):
        a = _manifest_zip(self, [_palette_entry(1), _palette_entry(2),
                                 _palette_entry(3)], name="a.amazepkg")
        b = _manifest_zip(self, [_palette_entry(4), _palette_entry(5),
                                 _palette_entry(6)], name="b.amazepkg")
        tree = [("defaults", "a.amazepkg", self.URL + "defaults/a.amazepkg"),
                ("defaults", "b.amazepkg", self.URL + "defaults/b.amazepkg")]
        bundles = {tree[0][2]: a, tree[1][2]: b}
        return _canned_amaze_source(tree, bundles)

    def test_every_asset_in_every_package_is_a_tile(self):
        source = self._two_package_folder()
        records = source.list_materials(limit=100)
        self.assertEqual(6, len(records),
                         "two packages of three assets must show six "
                         "tiles, the package invisible")
        self.assertEqual({"Defaults"}, {r.category for r in records})
        self.assertEqual({"amazepkg"}, {r.kind for r in records})
        self.assertEqual(6, len({r.uid for r in records}),
                         "tile uids collide across packages")

    def test_palette_records_carry_their_colours(self):
        source = self._two_package_folder()
        record = source.list_materials(limit=100)[0]
        self.assertEqual(["#101010", "#f0f0f0"],
                         record.payload.get("colors"),
                         "the swatch cannot be drawn client-side")
        self.assertTrue(record.payload.get("entry"),
                        "the manifest entry does not ride the record, "
                        "so importing needs a second manifest read")

    def test_material_records_name_their_thumbnail_member(self):
        entry = {"type": "asset", "section": "material", "id": "f" * 32,
                 "record": {"id": "f" * 32, "name": "Brick",
                            "categories": ["Import"]},
                 "note": {},
                 "files": {"mat": "assets/material/x/x.mat",
                           "thumbnail": "assets/material/x/x.png"}}
        pkg = _manifest_zip(self, [entry],
                            members={"assets/material/x/x.mat": b"payload",
                                     "assets/material/x/x.png": b"png"})
        url = self.URL + "defaults/m.amazepkg"
        source = _canned_amaze_source(
            [("defaults", "m.amazepkg", url)], {url: pkg})
        record = source.list_materials(limit=10)[0]
        self.assertEqual("assets/material/x/x.png",
                         record.payload.get("thumb_member"))

    def test_a_chosen_tile_icon_outranks_thumbnail_and_swatch(self):
        entry = {"type": "asset", "section": "gradient", "id": "a" * 32,
                 "record": {"id": "a" * 32, "name": "Customized",
                            "categories": ["X"],
                            "colors": [{"hex": "#101010"}]},
                 "note": {},
                 "files": {"thumbnail": "assets/gradient/a/a.png",
                           "tile_icon": "assets/gradient/a/a_icon.png"}}
        pkg = _manifest_zip(self, [entry],
                            members={"assets/gradient/a/a.png": b"p",
                                     "assets/gradient/a/a_icon.png": b"i"})
        url = self.URL + "defaults/c.amazepkg"
        source = _canned_amaze_source(
            [("defaults", "c.amazepkg", url)], {url: pkg})
        record = source.list_materials(limit=10)[0]
        self.assertEqual(
            "assets/gradient/a/a_icon.png",
            record.payload.get("thumb_member"),
            "the chosen icon must outrank the thumbnail online, the "
            "way every local section ranks it")

    def test_search_filters_by_title(self):
        source = self._two_package_folder()
        hits = source.list_materials(search="palette 4", limit=100)
        self.assertEqual(["Palette 4"], [r.title for r in hits])

    def test_refresh_drops_the_tree_and_manifest_caches(self):
        source = self._two_package_folder()
        source.list_materials(limit=100)
        source.list_materials(limit=100)
        self.assertEqual(1, type(source).tree_calls,
                         "browsing twice fetched the tree twice")
        self.assertEqual(2, len(type(source).open_calls),
                         "manifests were re-read on the second browse")
        source.refresh()
        source.list_materials(limit=100)
        self.assertEqual(2, type(source).tree_calls)
        self.assertEqual(4, len(type(source).open_calls),
                         "refresh did not drop the manifest cache - "
                         "the re-browse never re-opened the packages")

    def test_amaze_is_a_registered_source(self):
        from amaze.core import matx_sources
        names = [cls.name for cls in matx_sources.SOURCES]
        self.assertIn("Amaze", names)

    def test_a_newer_format_package_lists_no_tiles(self):
        new = _manifest_zip(self, [_palette_entry(7)],
                            name="future.amazepkg", fmt=99)
        old = _manifest_zip(self, [_palette_entry(1), _palette_entry(2),
                                   _palette_entry(3)], name="a.amazepkg")
        tree = [("defaults", "future.amazepkg",
                 self.URL + "defaults/future.amazepkg"),
                ("defaults", "a.amazepkg", self.URL + "defaults/a.amazepkg")]
        source = _canned_amaze_source(tree, {tree[0][2]: new,
                                             tree[1][2]: old})
        records = source.list_materials(limit=100)
        self.assertEqual(
            3, len(records),
            "a package of a NEWER format than this build reads must "
            "list no tiles - importing it would silently misread it - "
            "while the readable package beside it still shows")

    def test_a_store_package_is_refused_by_the_local_reader(self):
        """A store package with no manifest is refused by name, as a local one is."""
        from amaze.core import packages
        folder = tempfile.mkdtemp(prefix="amaze_store_pkg_")
        self.addCleanup(__import__("shutil").rmtree, folder, True)
        bare = os.path.join(folder, "bare.amazepkg")
        with zipfile.ZipFile(bare, "w") as bundle:
            bundle.writestr("readme.txt", "no manifest here")
        url = self.URL + "defaults/bare.amazepkg"
        source = _canned_amaze_source([("defaults", "bare.amazepkg", url)],
                                      {url: bare})
        with self.assertRaises(packages.PackageError) as caught:
            source._manifest(url)
        self.assertIn("not an Amaze package", str(caught.exception))


class RangedFileTest(unittest.TestCase):
    """zipfile over ranged reads: a block-cached RangedFile reads a MULTI-block zip whole and cheap, and _open_package's suffix-range seeding survives contact with a Range-speaking server."""

    PAYLOAD = bytes(range(256)) * 800    # 204,800 bytes - four blocks, so boundary crossings and the block cache are real, not vacuously green on a one-block fixture

    def test_a_zip_reads_whole_and_cheap_through_ranges(self):
        from amaze.core import matx_sources
        pkg = _manifest_zip(self, [_palette_entry(n) for n in range(40)],
                            members={"files/0_big.bin": self.PAYLOAD})
        blob = _bytes(pkg)
        self.assertGreater(len(blob), 3 * matx_sources.RANGED_BLOCK,
                           "premise: the fixture must span blocks")
        requests = []

        def get_range(start, end):
            requests.append((start, end))
            return blob[start:end + 1]

        remote = matx_sources.RangedFile(len(blob), get_range)
        with zipfile.ZipFile(remote) as bundle:
            from amaze.core import packages
            manifest = json.loads(bundle.read(packages.MANIFEST))
            self.assertEqual(self.PAYLOAD, bundle.read("files/0_big.bin"),
                             "a member spanning block boundaries did "
                             "not read back byte-identical")
        self.assertEqual(40, len(manifest["entries"]))
        self.assertLessEqual(
            len(requests), 8,
            "the block cache is not working - %d range requests for a "
            "%d-byte zip" % (len(requests), len(blob)))

    def test_a_known_small_package_is_fetched_whole_in_one_request(self):
        from unittest import mock

        from amaze.core import matx_sources, packages
        pkg = _manifest_zip(self, [_palette_entry(n) for n in range(3)])
        blob = _bytes(pkg)
        url = ("https://raw.githubusercontent.com/Timour/AmazePackages/"
               "main/packages/defaults/tiny.amazepkg")
        tree_json = {"tree": [{"type": "blob",
                               "path": "packages/defaults/tiny.amazepkg",
                               "size": len(blob)}]}
        calls = []

        class _Resp:
            def __init__(self, data):
                self._data, self.headers = data, {}

            def read(self):
                return self._data

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

        def counting(url_, headers=None):
            calls.append(headers or {})
            return _Resp(blob)

        source = matx_sources.AmazeSource()
        with mock.patch.object(matx_sources, "get_json",
                               return_value=tree_json):
            with mock.patch.object(matx_sources, "_request", counting):
                records = source.list_materials(limit=10)
        self.assertEqual(3, len(records))
        self.assertEqual(
            1, len(calls),
            "the tree already NAMES the size - a package under one "
            "block must be fetched whole in ONE request, not probe-"
            "416-refetch (%s)" % calls)
        self.assertNotIn("Range", calls[0],
                         "the single fetch must be plain, not ranged")

    def test_a_package_smaller_than_a_block_survives_a_416(self):
        from unittest import mock
        from urllib import error as uerror

        from amaze.core import matx_sources, packages
        pkg = _manifest_zip(self, [_palette_entry(n) for n in range(3)])
        blob = _bytes(pkg)
        self.assertLess(len(blob), matx_sources.RANGED_BLOCK,
                        "premise: the package must be under one block")

        class _Resp:
            def __init__(self, data):
                self._data, self.headers = data, {}

            def read(self):
                return self._data

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

        def strict_cdn(url, headers=None):
            spec = str((headers or {}).get("Range") or "")
            if spec.startswith("bytes=-"):
                if int(spec.split("-", 1)[1]) >= len(blob):    # raw.githubusercontent answers 416, not the RFC's whole file ▸r/github-ranged-store
                    raise uerror.HTTPError(url, 416,
                                           "Range Not Satisfiable",
                                           {}, None)
                start = len(blob) - int(spec.split("-", 1)[1])
                return _Resp(blob[start:])
            if spec:
                lo, _, hi = spec.replace("bytes=", "").partition("-")
                return _Resp(blob[int(lo):min(int(hi), len(blob) - 1)
                                  + 1])
            return _Resp(blob)

        url = ("https://raw.githubusercontent.com/Timour/AmazePackages/"
               "main/packages/defaults/tiny.amazepkg")
        source = matx_sources.AmazeSource()
        with mock.patch.object(matx_sources, "_request", strict_cdn):
            bundle = source._open_package(url)
            manifest = json.loads(bundle.read(packages.MANIFEST))
        self.assertEqual(3, len(manifest["entries"]),
                         "a sub-block package must survive the CDN's "
                         "416 on the oversized suffix probe - all five "
                         "store defaults are this size")

    def test_ranged_reads_report_block_progress(self):
        from amaze.core import matx_sources
        pkg = _manifest_zip(self, [_palette_entry(n) for n in range(3)],
                            members={"files/0_big.bin": self.PAYLOAD})
        blob = _bytes(pkg)
        seen = []

        def get_range(start, end):
            return blob[start:end + 1]

        remote = matx_sources.RangedFile(
            len(blob), get_range,
            notify=lambda done, total: seen.append((done, total)))
        with zipfile.ZipFile(remote) as bundle:
            bundle.read("files/0_big.bin")
        self.assertGreater(
            len(seen), 1,
            "a multi-block read reported no per-block progress - the "
            "UI freezes for the whole transfer with nothing pumping")
        dones = [d for d, _t in seen]
        self.assertEqual(sorted(set(dones)), dones,
                         "block progress must be non-decreasing")
        self.assertTrue(all(t == seen[0][1] for _d, t in seen),
                        "the block total drifted mid-read")

    def test_a_progress_callback_runs_only_on_the_thread_that_installed_it(self):
        """A reader's progress moves a bar; another thread reading the same file must not run it."""
        import threading

        from amaze.core import matx_sources
        remote = matx_sources.RangedFile(
            len(self.PAYLOAD),
            lambda start, end: self.PAYLOAD[start:end + 1])
        called_on = []
        remote.notify = (
            lambda done, total: called_on.append(threading.get_ident()))

        def read_block(index):
            remote.seek(index * matx_sources.RANGED_BLOCK)
            remote.read(16)

        worker = threading.Thread(target=read_block, args=(0,))
        worker.start()
        worker.join()
        self.assertEqual(
            [], called_on,
            "a preview worker's read ran the import's progress hook - "
            "widget work and an event pump off the GUI thread")
        read_block(1)
        self.assertEqual(
            [threading.get_ident()], called_on,
            "the import's own read no longer reports its progress")

    def test_open_package_seeds_from_a_suffix_range_and_caches(self):
        from unittest import mock

        from amaze.core import matx_sources, packages
        pkg = _manifest_zip(self, [_palette_entry(n) for n in range(3)],
                            members={"files/0_big.bin": self.PAYLOAD})
        blob = _bytes(pkg)
        calls = []

        class _Resp:
            def __init__(self, data, headers):
                self._data, self.headers = data, headers

            def read(self):
                return self._data

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

        def fake_request(url, headers=None):
            spec = str((headers or {}).get("Range") or "")
            calls.append(spec)
            lo, _, hi = spec.replace("bytes=", "").partition("-")
            if not lo:    # suffix range, the tail probe: bytes=-N
                start = max(0, len(blob) - int(hi))
                end = len(blob) - 1
            else:
                start, end = int(lo), min(int(hi), len(blob) - 1)
            return _Resp(blob[start:end + 1],
                         {"Content-Range": "bytes %d-%d/%d"
                          % (start, end, len(blob))})

        url = ("https://raw.githubusercontent.com/Timour/AmazePackages/"
               "main/packages/defaults/big.amazepkg")
        source = matx_sources.AmazeSource()
        with mock.patch.object(matx_sources, "_request", fake_request):
            bundle = source._open_package(url)
            manifest = json.loads(bundle.read(packages.MANIFEST))
            self.assertEqual(self.PAYLOAD, bundle.read("files/0_big.bin"))
            opened_in = len(calls)
            self.assertIs(bundle, source._open_package(url),
                          "the bundle was not cached")
        self.assertEqual(3, len(manifest["entries"]))
        self.assertTrue(calls[0].startswith("bytes=-"),
                        "the first request must be the suffix probe "
                        "that seeds the last block")
        self.assertLessEqual(opened_in, 8, calls)
        source.refresh()
        self.assertEqual({}, source._bundles,
                         "Refresh left a stale remote zip open")

    def test_two_threads_opening_one_package_share_one_reader(self):
        """A preview worker and the import may open one package at the same moment."""
        import threading
        from unittest import mock

        from amaze.core import matx_sources
        pkg = _manifest_zip(self, [_palette_entry(n) for n in range(3)],
                            members={"files/0_big.bin": self.PAYLOAD})
        url = ("https://raw.githubusercontent.com/Timour/AmazePackages/"
               "main/packages/defaults/race.amazepkg")
        inside, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def stall_the_first(_spec):
            if threading.current_thread().name == "first-opener":
                inside.set()
                release.wait(10)

        source = matx_sources.AmazeSource()
        opened = {}

        def open_as(name):
            opened[name] = source._open_package(url)

        with mock.patch.object(matx_sources, "_request",
                               _ranged_server(_bytes(pkg), stall_the_first)):
            first = threading.Thread(target=open_as, args=("first",),
                                     name="first-opener")
            first.start()
            self.assertTrue(inside.wait(5),
                            "premise: the first opener never fetched")
            second = threading.Thread(target=open_as, args=("second",),
                                      name="second-opener")
            second.start()
            second.join(10)
            release.set()
            first.join(10)
        self.assertIs(opened["first"], opened["second"],
                      "two threads opening one package got two readers")
        self.assertEqual([url], list(source._bundles))


class OnlinePackageImportTest(unittest.TestCase):
    """Selected TILES import - only their members, fresh into Import or restore adopt-only - and a corrupt member counts refused without abandoning the batch (CRC is corruption detection; authenticity rides TLS)."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    URL = "https://raw.githubusercontent.com/Timour/AmazePackages/main/"

    def _source_over(self, *fixture_ids):
        from amaze.core import packages
        model = self.panel.gradient_model
        items = [packages.collect_asset(model, mat_id)
                 for mat_id in fixture_ids]
        out = _out_path(self, "tiles.amazepkg")
        packages.write_package(out, items)
        url = self.URL + "defaults/tiles.amazepkg"
        return _canned_amaze_source(
            [("defaults", "tiles.amazepkg", url)], {url: out})

    def test_importing_one_selected_tile_lands_only_it(self):
        from unittest import mock
        model = self.panel.gradient_model
        ids = [str(a.mat_id) for a in model.assets[:3]]
        source = self._source_over(*ids)
        records = source.list_materials(limit=10)
        self.assertEqual(3, len(records), "premise: three tiles listed")
        chosen = records[1]
        before = model.rowCount()
        with mock.patch.object(self.panel.matx_online_model, "_sources",
                               [source]):    # the REAL _online_source_for runs - mocking it once hid a door that refused every amazepkg record over resolutions
            ok, reason = self.panel.import_online_material(chosen)
        self.assertTrue(ok, reason)
        self.assertEqual(before + 1, model.rowCount(),
                         "one selected tile did not import as one asset")
        newborn = model.assets[-1]
        self.assertEqual(chosen.title, newborn.name)
        cats = newborn.categories
        self.assertEqual(
            ["Import"], [cats] if isinstance(cats, str) else list(cats))

    def test_a_failed_note_write_still_counts_the_imported_asset(self):
        from unittest import mock

        from amaze.core import notes, packages
        model = self.panel.gradient_model
        items = [packages.collect_asset(model,
                                        str(model.assets[0].mat_id))]
        items[0]["note"] = {"items": [{"type": "text", "text": "kept"}]}
        out = _out_path(self, "noted.amazepkg")
        packages.write_package(out, items)
        url = self.URL + "defaults/noted.amazepkg"
        source = _canned_amaze_source(
            [("defaults", "noted.amazepkg", url)], {url: out})
        record = source.list_materials(limit=10)[0]
        before = model.rowCount()
        with mock.patch.object(self.panel.matx_online_model, "_sources",
                               [source]):
            with mock.patch.object(notes, "set_note",
                                   side_effect=OSError("notes full")):
                ok, reason = self.panel.import_online_material(record)
        self.assertTrue(
            ok, "the asset was imported and SAVED before its note page "
                "failed - reporting the tile as failed while it sits in "
                "the library lies twice (reason: %s)" % reason)
        self.assertEqual(before + 1, model.rowCount())

    def test_restore_selected_is_adopt_only(self):
        from unittest import mock
        model = self.panel.gradient_model
        present = str(model.assets[0].mat_id)
        source = self._source_over(present)
        record = source.list_materials(limit=10)[0]
        before = model.rowCount()
        with mock.patch.object(self.panel.matx_online_model, "_sources",
                               [source]):
            summary = self.panel.restore_amaze_packages([record])
        self.assertEqual(before, model.rowCount(),
                         "a still-present tile was duplicated by restore")
        self.assertEqual(1, summary["skipped"])

    def test_a_store_tile_import_drives_the_download_bar(self):
        from unittest import mock

        from amaze.core import matx_sources
        payload = RangedFileTest.PAYLOAD
        entry = {"type": "asset", "section": "material", "id": "9" * 32,
                 "record": {"id": "9" * 32, "name": "Big",
                            "categories": ["X"]},
                 "note": {},
                 "files": {"mat": "assets/material/9/9.mat"}}
        pkg = _manifest_zip(self, [entry],
                            members={"assets/material/9/9.mat": payload})
        blob = _bytes(pkg)

        class _Resp:
            def __init__(self, data, headers):
                self._data, self.headers = data, headers

            def read(self):
                return self._data

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

        def serve(url, headers=None):
            spec = str((headers or {}).get("Range") or "")
            if spec.startswith("bytes=-"):
                n = int(spec.split("-", 1)[1])
                start = max(0, len(blob) - n)
                return _Resp(blob[start:], {
                    "Content-Range": "bytes %d-%d/%d"
                    % (start, len(blob) - 1, len(blob))})
            if spec:
                lo, _, hi = spec.replace("bytes=", "").partition("-")
                return _Resp(blob[int(lo):min(int(hi), len(blob) - 1) + 1],
                             {})
            return _Resp(blob, {})

        tree_json = {"tree": [{"type": "blob",
                               "path": "packages/defaults/big.amazepkg",
                               "size": len(blob)}]}
        source = matx_sources.AmazeSource()
        fractions = []
        with mock.patch.object(matx_sources, "get_json",
                               return_value=tree_json):
            with mock.patch.object(matx_sources, "_request", serve):
                record = source.list_materials(limit=10)[0]
                with mock.patch.object(
                        self.panel.matx_online_model, "_sources",
                        [source]):
                    ok, reason = self.panel.import_online_material(
                        record, on_progress=fractions.append)
        self.assertTrue(ok, reason)
        self.assertGreater(
            len(fractions), 1,
            "the import reported only its end - the bar sat at zero "
            "and nothing pumped while the network ran, which is the "
            "frozen Houdini that has to be force-quit")
        self.assertEqual(1.0, fractions[-1])
        self.assertEqual(sorted(fractions), fractions,
                         "fractions must be non-decreasing")

    def test_the_import_never_waits_behind_a_preview_download(self):
        """A worker mid-download in the shared reader holds its lock; the import reads its own."""
        import threading
        import time
        from unittest import mock

        from amaze.core import matx_sources
        entry = {"type": "asset", "section": "material", "id": "8" * 32,
                 "record": {"id": "8" * 32, "name": "Behind",
                            "categories": ["X"]},
                 "note": {}, "files": {"mat": "assets/material/8/8.mat"}}
        pkg = _manifest_zip(self, [entry], members={
            "assets/material/8/8.mat": RangedFileTest.PAYLOAD,
            "thumbs/8.png": RangedFileTest.PAYLOAD[::-1]})
        blob = _bytes(pkg)
        inside, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def stall_the_worker(spec):
            if threading.current_thread().name == "preview-worker" \
                    and spec and not spec.startswith("bytes=-"):
                inside.set()
                release.wait(10)

        tree_json = {"tree": [{"type": "blob",
                               "path": "packages/defaults/behind.amazepkg",
                               "size": len(blob)}]}
        source = matx_sources.AmazeSource()
        watchdog = threading.Timer(4.0, release.set)
        self.addCleanup(watchdog.cancel)
        with mock.patch.object(matx_sources, "get_json",
                               return_value=tree_json), \
                mock.patch.object(matx_sources, "_request",
                                  _ranged_server(blob, stall_the_worker)):
            record = source.list_materials(limit=10)[0]
            url = record.payload["package"]
            worker = threading.Thread(
                target=lambda: source._open_package(url).read("thumbs/8.png"),
                name="preview-worker")
            worker.start()
            self.assertTrue(inside.wait(5),
                            "premise: the worker never reached the network")
            watchdog.start()
            started = time.monotonic()
            with mock.patch.object(self.panel.matx_online_model, "_sources",
                                   [source]):
                ok, reason = self.panel.import_online_material(record)
            waited = time.monotonic() - started
            release.set()
            worker.join(10)
        self.assertTrue(ok, reason)
        self.assertLess(
            waited, 2.0,
            "the import waited %.1fs behind a preview worker's block "
            "download, and Houdini is frozen for all of it" % waited)

    def test_a_corrupt_member_counts_refused_not_fatal(self):
        from unittest import mock
        entry = {"type": "asset", "section": "material", "id": "e" * 32,
                 "record": {"id": "e" * 32, "name": "Broken",
                            "categories": ["X"]},
                 "note": {},
                 "files": {"mat": "assets/material/e/e.mat"}}
        pkg = _manifest_zip(self, [entry],
                            members={"assets/material/e/e.mat": b"gooddata"})
        with open(pkg, "r+b") as handle:    # flip one payload byte so the member's own CRC refuses the read
            data = handle.read()
            at = data.index(b"gooddata")
            handle.seek(at)
            handle.write(b"baddata!")
        url = self.URL + "defaults/broken.amazepkg"
        source = _canned_amaze_source(
            [("defaults", "broken.amazepkg", url)], {url: pkg})
        record = source.list_materials(limit=10)[0]
        material_model = self.panel.material_model
        before = material_model.rowCount()
        with mock.patch.object(self.panel.matx_online_model, "_sources",
                               [source]):
            ok, reason = self.panel.import_online_material(record)
        self.assertFalse(ok, "a corrupt payload imported as good")
        self.assertIn("did not read back whole", reason,    # the COUNTED refusal, not a crash: an unbound `debug` in the handler once produced the same False through the catch-all
                      reason)
        self.assertEqual(before, material_model.rowCount(),
                         "the refused tile still changed the library")

    def test_the_online_menu_offers_restore_on_packages_only(self):
        from amaze.panel import sections
        labels = [e.label for e in sections.OnlineContext.GRID_MENU]
        self.assertIn("Restore", labels)
        entry = [e for e in sections.OnlineContext.GRID_MENU
                 if e.label == "Restore"][0]
        self.assertEqual("selection_is_amaze_packages", entry.shown,
                         "Restore must hide for material sources")


class TexturePackingTest(unittest.TestCase):
    """Format 2: an asset's adopted textures travel in the package - packed from the row's token inventory, landed at the same tokens in the receiving library, and a token that escapes the library is refused."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _material_with_texture(self, name):
        import hou

        from amaze.tests import make_library_fixture
        outside = tempfile.mkdtemp(prefix="amaze_outside_")
        self.addCleanup(
            __import__("shutil").rmtree, outside, ignore_errors=True)
        source = os.path.join(outside, "weave_diff.png")
        with open(source, "wb") as handle:
            handle.write(b"weavebytes")
        builder = make_library_fixture.build_material(
            hou.node("/mat"), name, (0.4, 0.4, 0.4))
        self.addCleanup(builder.destroy)
        image = builder.createNode("mtlximage")
        image.parm("file").set(source)
        model = self.panel.material_model
        self.assertTrue(model.add_asset(builder, "Fabrics", "", False),
                        "premise: the save went through")
        return model, model.assets[-1]

    def test_export_packs_the_texture_inventory(self):
        from amaze.core import packages
        model, row = self._material_with_texture("Packed_Weave")
        entry = packages.collect_asset(model, str(row.mat_id))
        textures = entry.get("textures") or {}
        self.assertEqual(1, len(textures),
                         "the token inventory was not collected")
        token = next(iter(textures))
        self.assertTrue(token.startswith("$AMAZELIB/matX/"), token)
        out = _out_path(self, "weave.amazepkg")
        packages.write_package(out, [entry])
        with zipfile.ZipFile(out) as bundle:
            manifest = json.loads(bundle.read(packages.MANIFEST))
            self.assertEqual(2, manifest["format"],
                             "textures need format 2 - a format-1 "
                             "reader would import silently bare")
            arc = manifest["entries"][0]["textures"][token]
            self.assertEqual(b"weavebytes", bundle.read(arc))

    def test_import_lands_textures_at_their_tokens(self):
        from amaze.core import packages, texstore
        model, row = self._material_with_texture("Landed_Weave")
        out = _out_path(self, "landed.amazepkg")
        packages.write_package(
            out, [packages.collect_asset(model, str(row.mat_id))])
        adopted = texstore.resolve(
            (row.get_as_dict().get("textures") or [""])[0],
            model.preferences)
        os.remove(adopted)    # the package must be the only source, as in a foreign library - same-library resolve would green this vacuously
        before = model.rowCount()
        summary = self.panel.import_package_file(out)
        self.assertEqual(1, summary["imported"], summary)
        self.assertEqual(before + 1, model.rowCount())
        newborn = model.assets[-1]
        tokens = newborn.get_as_dict().get("textures") or []
        self.assertEqual(1, len(tokens),
                         "the imported row lost its inventory")
        landed = texstore.resolve(tokens[0], model.preferences)
        self.assertTrue(os.path.isfile(landed),
                        "the texture member did not land at its token")

    def test_a_token_escaping_the_library_is_refused(self):
        from amaze.core import packages
        model = self.panel.material_model
        entry = {"type": "asset", "section": "material", "id": "d" * 32,
                 "record": {"id": "d" * 32, "name": "Escape",
                            "categories": ["X"],
                            "textures": ["$AMAZELIB/../outside.png"]},
                 "note": {}, "files": {},
                 "textures": {"$AMAZELIB/../outside.png":
                              "assets/material/d/textures/0_outside.png"}}
        pkg = _manifest_zip(
            self, [entry],
            members={"assets/material/d/textures/0_outside.png": b"evil"})
        before = model.rowCount()
        summary = packages.import_package(
            self.panel._package_models(), self.panel.prefs, pkg)
        self.assertEqual(1, summary["refused"], summary)
        self.assertEqual(before, model.rowCount(),
                         "the escaping entry still landed a row")
        outside = os.path.normpath(os.path.join(
            str(model.preferences.dir), os.pardir, "outside.png"))
        self.assertFalse(os.path.exists(outside),
                         "a token walked out of the library")

    def test_a_token_outside_the_store_is_refused(self):
        from amaze.core import packages
        model = self.panel.material_model
        entry = {"type": "asset", "section": "material", "id": "c" * 32,
                 "record": {"id": "c" * 32, "name": "Control",
                            "categories": ["X"]},
                 "note": {}, "files": {},
                 "textures": {"$AMAZELIB/policy.json":
                              "assets/material/c/textures/0_policy.json"}}
        pkg = _manifest_zip(
            self, [entry],
            members={"assets/material/c/textures/0_policy.json": b"{}"})
        before = model.rowCount()
        summary = packages.import_package(
            self.panel._package_models(), self.panel.prefs, pkg)
        self.assertEqual(1, summary["refused"],
                         "a token aimed at the library's own control "
                         "files must refuse - contained is not enough, "
                         "it must land under matX/")
        self.assertEqual(before, model.rowCount())
        self.assertFalse(os.path.exists(os.path.join(
            str(model.preferences.dir), "policy.json")),
            "a package minted a policy file for the library")


class OnlineKindFilterTest(unittest.TestCase):
    """The online eye: All / Materials / Colors / Nodes / Code narrows the grid by tile KIND - non-Amaze sources count as Materials, the choice holds for the session."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _mixed_records(self):
        from amaze.core import matx_sources

        def store(section, n):
            return matx_sources.MatxRecord(
                source="Amaze", uid="d/p.amazepkg#%d" % n, title="T%d" % n,
                category="Defaults", kind="amazepkg",
                payload={"package": "https://x", "section": section,
                         "entry": {}})
        return [store("gradient", 1), store("code", 2), store("cop", 3),
                store("material", 4),
                matx_sources.MatxRecord(source="GPUOpen", uid="g1",
                                        title="Brick", category="Stone",
                                        kind="package", payload={})]

    def test_the_kind_filter_narrows_by_what_a_tile_is(self):
        from amaze.core import matx_library
        model = matx_library.MatxOnlineLibrary(
            preferences=type("P", (), {"rendersize": 64})())
        model._all = self._mixed_records()
        model._loaded = True
        model.set_kind_filter("gradient")
        self.assertEqual(["T1"], [r.title for r in model._records])
        model.set_kind_filter("material")
        self.assertEqual(["T4", "Brick"],
                         [r.title for r in model._records],
                         "a non-Amaze source tile IS a material and "
                         "must survive the Materials filter")
        model.set_kind_filter(None)
        self.assertEqual(5, len(model._records))

    def test_build_filter_menu_leaves_the_online_eye_alone(self):
        panel = self.panel
        panel.enter_online_world()
        try:
            panel.build_filter_menu()
            self.assertIn(
                "Show one kind of tile", panel.btn_filter.toolTip(),
                "build_filter_menu clobbered the kind filter's tooltip "
                "- two owners of one control")
            self.assertEqual(
                ["All", "Materials", "Colors", "Nodes", "Code"],
                [a.text() for a in panel.btn_filter.menu().actions()])
        finally:
            panel.leave_online_world()

    def test_the_tile_labels_are_the_sections_own(self):
        from amaze.core import matx_library
        from amaze.panel import sections
        labels = matx_library.SECTION_TILE_LABELS
        self.assertEqual({"gradient", "cop", "code", "file"},
                         set(labels))
        for cls in sections.SECTION_CLASSES:
            if cls.key in labels:
                self.assertEqual(
                    cls.label, labels[cls.key],
                    "the online subtitle for %r drifted from the "
                    "section's own label" % cls.key)

    def test_the_online_eye_offers_the_five_kinds(self):
        panel = self.panel
        panel.enter_online_world()
        try:
            self.assertTrue(
                panel.btn_filter.isEnabled(),
                "the EYE (the Filter button - icon_view.svg is its "
                "face) stayed disabled online, which is the whole ask")
            menu = panel.btn_filter.menu()
            self.assertEqual(["All", "Materials", "Colors", "Nodes",
                              "Code"],
                             [a.text() for a in menu.actions()])
            checked = [a.text() for a in menu.actions() if a.isChecked()]
            self.assertEqual(["All"], checked)
            colors = next(a for a in menu.actions()
                          if a.text() == "Colors")
            colors.trigger()
            self.assertEqual("gradient",
                             panel.matx_online_model._kind_filter)
        finally:
            panel.leave_online_world()
        self.assertNotIn(
            "Colors",
            [a.text() for a in panel.btn_filter.menu().actions()],
            "leaving the world must hand the eye its section filter "
            "menu back")


class OnlineTilePaintingTest(unittest.TestCase):
    """The browser's tile pictures without full downloads: palette swatches DRAWN from the record's colours, material thumbnails fetched per member through a callable preview job."""

    def test_a_swatch_is_the_color_sections_own_face(self):
        from amaze.core import gradient_library
        image = gradient_library.paint_swatch(
            [{"hex": "#ff0000"}, {"hex": "#0000ff"}], {})
        size = gradient_library.THUMB_SIZE
        self.assertEqual((size, size), (image.width(), image.height()))
        top = image.pixelColor(size // 2, size // 4)
        bottom = image.pixelColor(size // 2, 3 * size // 4)
        self.assertGreater(top.red(), 200,
                           "the top band is not the first colour - the "
                           "Color section stacks HORIZONTAL bands")
        self.assertGreater(bottom.blue(), 200)

    def test_an_online_palette_paints_the_local_face(self):
        from amaze.core import (gradient_library, matx_library,
                                matx_sources, thumbnails)
        record = matx_sources.MatxRecord(
            source="Amaze", uid="d/p.amazepkg#s", title="Two",
            category="Defaults", kind="amazepkg",
            payload={"package": "https://x", "section": "gradient",
                     "entry": {"record": {
                         "colors": [{"hex": "#ff0000"},
                                    {"hex": "#0000ff"}]}},
                     "colors": ["#ff0000", "#0000ff"]})
        model = matx_library.MatxOnlineLibrary(
            preferences=type("P", (), {"rendersize": 64})())
        key = model._preview_key(record)
        thumbnails.engine.discard(key)
        model._queue_previews([record])
        image = thumbnails.engine.peek(key)
        self.assertIsNotNone(image)
        self.assertEqual(
            gradient_library.paint_swatch(
                [{"hex": "#ff0000"}, {"hex": "#0000ff"}], {}),
            image,
            "the online palette face differs from the Color section's "
            "for the same colours - a second painter has crept in")

    def test_a_thumbless_tile_shows_its_sections_own_face(self):
        from amaze.core import cop_library, library, matx_library, \
            matx_sources, thumbnails, tile_icons
        model = matx_library.MatxOnlineLibrary(
            preferences=type("P", (), {"rendersize": 64})())

        def face_of(section, record):
            rec = matx_sources.MatxRecord(
                source="Amaze", uid="d/p.amazepkg#" + section,
                title="T", category="Defaults", kind="amazepkg",
                payload={"package": "https://x", "section": section,
                         "entry": {"record": record}})
            key = model._preview_key(rec)
            thumbnails.engine.discard(key)
            model._queue_previews([rec])
            return thumbnails.engine.peek(key)

        node = face_of("cop", {"name": "domelight1", "renderer": "LOP"})
        self.assertIsNotNone(
            node, "a node tile with no packed thumbnail stayed BLANK")
        self.assertEqual(
            tile_icons.generic_image(cop_library.CopLibrary.TILE_FACE), node,
            "a node tile online must wear the Node section's own generic "
            "face, not a hand-picked one")
        self.assertEqual(
            tile_icons.generic_image(library.MaterialLibrary.TILE_FACE),
            face_of("material", {"name": "bare"}),
            "a thumbless material wears the Material section's generic face")

    def test_the_value_only_template_takes_both_swatches(self):
        """T09's two placeholder colours are swapped for the values in either case of hex."""
        from amaze.core import matx_icon
        svg = matx_icon.icon_svg({"color": [1.0, 0.0, 0.0], "transmission": 0.5}).lower()
        self.assertNotIn(matx_icon._BASE_PLACEHOLDER, svg, "the base colour swatch kept its placeholder")
        self.assertNotIn(matx_icon._SWATCH2_PLACEHOLDER, svg, "the second swatch kept its placeholder")
        self.assertIn('fill="#ff0000"', svg)
        self.assertIn('fill-opacity="%s"' % matx_icon.TRANSMISSIVE_ALPHA, svg)

    def test_a_thumb_member_outranks_the_swatch_and_the_code_paint(self):
        from amaze.core import matx_library, matx_sources, thumbnails
        record = matx_sources.MatxRecord(
            source="Amaze", uid="defaults/c.amazepkg#a",
            title="Customized", category="Defaults", kind="amazepkg",
            payload={"package": "https://x", "entry": {}, "section":
                     "gradient", "colors": ["#101010"],
                     "thumb_member": "assets/gradient/a/a_icon.png"})
        model = matx_library.MatxOnlineLibrary(
            preferences=type("P", (), {"rendersize": 64})())
        key = model._preview_key(record)
        thumbnails.engine.discard(key)
        model._queue_previews([record])
        self.assertIsNone(
            thumbnails.engine.peek(key),
            "a swatch was painted over a record that NAMES its icon - "
            "the chosen icon must outrank the drawn preview, the way "
            "every local section ranks it")

    def test_store_tiles_are_labelled_by_what_they_are(self):
        from amaze.core import matx_library, matx_sources
        model = matx_library.MatxOnlineLibrary(
            preferences=type("P", (), {"rendersize": 64})())
        cases = [("material", {"renderer": "Redshift"}, "Redshift"),
                 ("material", {"renderer": "Karma"}, "Karma"),
                 ("material", {}, "Material"),
                 ("gradient", {}, "Color"),
                 ("cop", {}, "Node"),
                 ("code", {"renderer": "VEX"}, "Code")]
        for section, record, wanted in cases:
            rec = matx_sources.MatxRecord(
                source="Amaze", uid="d/p.amazepkg#x", title="T",
                category="Defaults", kind="amazepkg",
                payload={"package": "https://x", "section": section,
                         "entry": {"record": record}})
            model._records = [rec]
            got = model.data(model.index(0, 0),
                             model.RendererLabelRole)
            self.assertEqual(
                wanted, got,
                "a %s store tile must say what it IS, not "
                "'Amaze (values)'" % section)

    def test_a_snippet_tile_paints_its_code(self):
        from amaze.core import matx_library, matx_sources, thumbnails
        from amaze.helpers import vex_syntax
        entry = {"type": "asset", "section": "code", "id": "b" * 32,
                 "record": {"id": "b" * 32, "name": "Jitter",
                            "categories": ["Toolbox"], "renderer": "VEX",
                            "code": "@P += rand(@ptnum);"},
                 "note": {}, "files": {}}
        record = matx_sources.MatxRecord(
            source="Amaze", uid="defaults/t.amazepkg#b", title="Jitter",
            category="Defaults", kind="amazepkg",
            payload={"package": "https://x", "entry": entry,
                     "section": "code"})
        model = matx_library.MatxOnlineLibrary(
            preferences=type("P", (), {"rendersize": 64})())
        key = model._preview_key(record)
        thumbnails.engine.discard(key)
        model._queue_previews([record])
        image = thumbnails.engine.peek(key)
        self.assertIsNotNone(
            image, "a code snippet tile stayed BLANK - 15 invisible "
                   "tiles in a grid of colours is a package that "
                   "'does not show up'")
        self.assertEqual(image.pixelColor(2, 2).name(),
                         vex_syntax.BACKGROUND.name(),
                         "the snippet preview is not the wrangle-"
                         "editor field the Code section paints")

    def _cached_preview(self, valid):
        """A model showing one URL record whose preview is already in the disk cache."""
        from PySide6 import QtGui

        from amaze.core import matx_library, matx_sources, thumbnails
        model = matx_library.MatxOnlineLibrary(
            preferences=type("P", (), {"rendersize": 64})())
        record = matx_sources.MatxRecord(
            source="PolyHaven", uid="d7-%s" % valid, title="Cached",
            category="Metal", preview_url="https://example.invalid/p.png")
        path = model._cache_path(record)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        if valid:
            canvas = QtGui.QImage(8, 8, QtGui.QImage.Format.Format_RGB32)
            canvas.fill(QtGui.QColor("#123456"))
            canvas.save(path, "PNG")
        else:
            with open(path, "wb") as handle:
                handle.write(b"not an image")
        model._records = [record]
        model._key_rows = {model._preview_key(record): 0}
        model._flush_pending = lambda: None
        key = model._preview_key(record)
        thumbnails.engine.discard(key)
        self.addCleanup(thumbnails.engine.discard, key)
        return model, key

    def _settle(self, until):
        deadline = time.monotonic() + 10
        while not until() and time.monotonic() < deadline:
            QtWidgets.QApplication.processEvents()

    def test_a_cached_preview_is_decoded_off_the_gui_thread(self):
        from amaze.core import thumbnails
        model, key = self._cached_preview(True)
        index = model.index(0, 0)
        self.assertIsNone(
            model.data(index, QtCore.Qt.ItemDataRole.DecorationRole),
            "the cached preview was decoded inside data(), on the GUI "
            "thread")
        self._settle(lambda: thumbnails.engine.peek(key) is not None)
        self.assertIsNotNone(model.data(
            index, QtCore.Qt.ItemDataRole.DecorationRole),
            "the off-thread load never landed")
        self.assertEqual([], model._pending, "a cached preview was "
                                             "queued for download")

    def test_a_cached_preview_that_will_not_decode_goes_to_the_worker(self):
        from amaze.core import thumbnails
        model, key = self._cached_preview(False)
        index = model.index(0, 0)
        model.data(index, QtCore.Qt.ItemDataRole.DecorationRole)
        self._settle(lambda: thumbnails.engine.is_missing(key))
        model.data(index, QtCore.Qt.ItemDataRole.DecorationRole)
        self.assertEqual([key], [model._preview_key(r)
                                 for r in model._pending],
                         "a broken cached preview never reached the "
                         "worker that clears it")

    def test_a_preview_job_may_be_a_callable(self):
        from amaze.core import matx_library
        folder = tempfile.mkdtemp(prefix="amaze_prevjob_")
        self.addCleanup(
            __import__("shutil").rmtree, folder, ignore_errors=True)
        path = os.path.join(folder, "tile.png")

        def fetch(target):
            image = QtWidgets.QApplication.instance()    # any small valid png
            from PySide6 import QtGui
            canvas = QtGui.QImage(8, 8, QtGui.QImage.Format.Format_RGB32)
            canvas.fill(QtGui.QColor("#123456"))
            canvas.save(target, "PNG")

        worker = matx_library._PreviewWorker([("k", fetch, path)])
        seen = []
        worker.ready.connect(lambda key, img: seen.append((key, img)))
        worker.run()
        self.assertEqual(1, len(seen),
                         "the callable job never produced an image")
        self.assertFalse(seen[0][1].isNull())


if __name__ == "__main__":
    unittest.main()
