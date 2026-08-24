"""The `.amazepkg` format: export collects an asset's REAL file family plus its note page, plain files ride with their kind, the zip lands guarded and whole, and the reader refuses a format newer than it speaks."""

import json
import os
import sys
import tempfile
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


class _Cats:
    _categories = []    # the rename helper reads the sidebar list; empty means nothing to rename

    def check_add_category(self, name):
        pass


class CuratedKeysTest(unittest.TestCase):
    """The stable identity under the defaults: every seeded row carries a `curated` tag (riding `_extra`, no schema work), and restore unions by the TAG where one exists - the same palette in two libraries has two ids but one tag."""

    def _fresh_prefs(self, marker):
        p = test_support.fixture_prefs(self)
        for name in (marker, marker.replace("amaze", "assetlib")):
            try:
                os.remove(os.path.join(p.dir, name))
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
        untagged = [a.name for a in fresh
                    if not (getattr(a, "_extra", None) or {}).get("curated")]
        self.assertEqual([], untagged[:5],
                         "seeded palettes carry no curated tag")
        sets_seen = {str((getattr(a, "_extra", None) or {})
                         .get("curated", "")).split("/")[0]
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
                    if not str((getattr(a, "_extra", None) or {})
                               .get("curated", "")).startswith("starter/")]
        self.assertEqual([], untagged[:5],
                         "seeded snippets carry no starter/ tag")

    def test_a_deleted_default_comes_back_from_the_set_package(self):
        from amaze.core import gradient_library, packages
        p = self._fresh_prefs(".amaze_gradient_seed_v1")
        model = gradient_library.GradientLibrary(p)
        model.seed_curated_palettes(_Cats())
        wada = [a for a in model._assets
                if str((getattr(a, "_extra", None) or {})
                       .get("curated", "")).startswith("wada/")]
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


class _CannedAmazeSource:
    """The AmazeSource with its one network door overridden - built lazily inside tests so the class import happens after the module exists."""

    def __new__(cls, index_bytes, files):
        from amaze.core import matx_sources

        class Source(matx_sources.AmazeSource):
            calls = []

            def _get(self, url):
                Source.calls.append(url)
                if url.endswith("index.json"):
                    return index_bytes
                return files[url]

        return Source()


class AmazeSourceTest(unittest.TestCase):
    """The fifth online source: the index is the catalogue, folders are categories, fetch verifies the checksum, and Refresh drops the cache."""

    def _store(self):
        import hashlib
        from amaze.core import packages
        folder = tempfile.mkdtemp(prefix="amaze_store_src_")
        self.addCleanup(
            __import__("shutil").rmtree, folder, ignore_errors=True)
        source_file = os.path.join(folder, "a.txt")
        with open(source_file, "w") as handle:
            handle.write("x")
        pkg = os.path.join(folder, "mini.amazepkg")
        packages.write_package(
            pkg, [packages.collect_file(source_file, "other")])
        blob = _bytes(pkg)
        base = "https://raw.githubusercontent.com/Timour/AmazePackages/main/"
        index = {
            "format": 1, "base": base,
            "categories": [{"name": "defaults", "packages": [{
                "name": "mini", "file": "defaults/mini.amazepkg",
                "bytes": len(blob), "entries": 1,
                "kinds": {"other": 1}, "package_format": 1,
                "sha256": hashlib.sha256(blob).hexdigest()}]}]}
        return (json.dumps(index).encode("utf-8"),
                {base + "defaults/mini.amazepkg": blob})

    def test_the_index_lists_as_records_with_folder_categories(self):
        index_bytes, files = self._store()
        source = _CannedAmazeSource(index_bytes, files)
        records = source.list_materials()
        self.assertEqual(1, len(records))
        record = records[0]
        self.assertEqual("mini", record.title)
        self.assertEqual("Defaults", record.category)
        self.assertEqual("amazepkg", record.kind)
        self.assertTrue(record.payload.get("url", "").startswith("https://"))

    def test_fetch_verifies_the_checksum_and_lands_the_file(self):
        index_bytes, files = self._store()
        source = _CannedAmazeSource(index_bytes, files)
        record = source.list_materials()[0]
        dest = tempfile.mkdtemp(prefix="amaze_store_dl_")
        self.addCleanup(
            __import__("shutil").rmtree, dest, ignore_errors=True)
        got = source.fetch(record, None, dest)
        self.assertTrue(got["amazepkg"].endswith(".amazepkg"))
        self.assertEqual(files[record.payload["url"]],
                         _bytes(got["amazepkg"]))

    def test_a_record_without_a_checksum_is_refused(self):
        from amaze.core import matx_sources
        record = matx_sources.MatxRecord(
            source="Amaze", uid="defaults/x.amazepkg", title="x",
            category="Defaults", kind="amazepkg",
            payload={"url": "https://raw.githubusercontent.com/x"})
        source = matx_sources.AmazeSource()
        dest = tempfile.mkdtemp(prefix="amaze_store_nosha_")
        self.addCleanup(
            __import__("shutil").rmtree, dest, ignore_errors=True)
        with self.assertRaises(Exception) as caught:
            source.fetch(record, None, dest)
        self.assertIn("checksum", str(caught.exception).lower())
        self.assertEqual([], os.listdir(dest),
                         "an unverifiable download still landed")

    def test_a_corrupt_download_is_refused_by_name(self):
        index_bytes, files = self._store()
        url = next(iter(files))
        files = dict(files, **{url: files[url] + b"tampered"})
        source = _CannedAmazeSource(index_bytes, files)
        record = source.list_materials()[0]
        dest = tempfile.mkdtemp(prefix="amaze_store_bad_")
        self.addCleanup(
            __import__("shutil").rmtree, dest, ignore_errors=True)
        with self.assertRaises(Exception) as caught:
            source.fetch(record, None, dest)
        self.assertIn("checksum", str(caught.exception).lower())

    def test_refresh_drops_the_cached_index(self):
        index_bytes, files = self._store()
        source = _CannedAmazeSource(index_bytes, files)
        source.list_materials()
        source.list_materials()
        index_calls = [u for u in type(source).calls
                       if u.endswith("index.json")]
        self.assertEqual(1, len(index_calls),
                         "browsing twice fetched the index twice")
        source.refresh()
        source.list_materials()
        index_calls = [u for u in type(source).calls
                       if u.endswith("index.json")]
        self.assertEqual(2, len(index_calls))

    def test_amaze_is_a_registered_source(self):
        from amaze.core import matx_sources
        names = [cls.name for cls in matx_sources.SOURCES]
        self.assertIn("Amaze", names)


class OnlinePackageImportTest(unittest.TestCase):
    """The world's one import door routes amazepkg records into the package import - fresh through the Import entries, adopt-only through Restore."""

    @classmethod
    def setUpClass(cls):
        cls.panel = test_support.fixture_panel(test_support.class_scope(cls))

    def _record_over(self, blob):
        import hashlib
        from amaze.core import matx_sources
        url = "https://raw.githubusercontent.com/Timour/AmazePackages/x.amazepkg"

        class Source(matx_sources.AmazeSource):
            def _get(self, _url):
                return blob

        record = matx_sources.MatxRecord(
            source="Amaze", uid="defaults/x.amazepkg", title="x",
            category="Defaults", kind="amazepkg",
            payload={"url": url,
                     "sha256": hashlib.sha256(blob).hexdigest()})
        return Source(), record

    def _gradient_blob(self):
        from amaze.core import packages
        model = self.panel.gradient_model
        item = packages.collect_asset(model, model.assets[0].mat_id)
        out = _out_path(self, "online.amazepkg")
        packages.write_package(out, [item])
        return _bytes(out)

    def test_the_library_door_imports_a_package_record_fresh(self):
        from unittest import mock
        source, record = self._record_over(self._gradient_blob())
        model = self.panel.gradient_model
        before = model.rowCount()
        with mock.patch.object(self.panel, "_online_source_for",
                               return_value=(source, None, "")):
            ok, reason = self.panel.import_online_material(record)
        self.assertTrue(ok, reason)
        self.assertEqual(before + 1, model.rowCount(),
                         "the package record never reached the library")
        cats = model._assets[-1].categories
        self.assertEqual(
            ["Import"], [cats] if isinstance(cats, str) else list(cats))

    def test_restore_from_online_unions_instead_of_copying(self):
        from unittest import mock
        source, record = self._record_over(self._gradient_blob())
        model = self.panel.gradient_model
        before = model.rowCount()
        with mock.patch.object(self.panel, "_online_source_for",
                               return_value=(source, None, "")):
            summary = self.panel.restore_amaze_packages([record])
        self.assertEqual(before, model.rowCount(),
                         "a still-present palette was duplicated by "
                         "restore")
        self.assertEqual(1, summary["skipped"])

    def test_the_online_menu_offers_restore_on_packages_only(self):
        from amaze.panel import sections
        labels = [e.label for e in sections.OnlineContext.GRID_MENU]
        self.assertIn("Restore", labels)
        entry = [e for e in sections.OnlineContext.GRID_MENU
                 if e.label == "Restore"][0]
        self.assertEqual("selection_is_amaze_packages", entry.shown,
                         "Restore must hide for material sources")


if __name__ == "__main__":
    unittest.main()
