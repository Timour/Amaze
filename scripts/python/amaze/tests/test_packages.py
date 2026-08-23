"""The `.amazepkg` format: export collects an asset's REAL file family plus its note page, plain files ride with their kind, the zip lands guarded and whole, and the reader refuses a format newer than it speaks."""

import json
import os
import sys
import tempfile
import unittest
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.tests import test_support  # noqa: E402


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
                    open(source, "rb").read(), bundle.read(arcname),
                    "member %r does not byte-match the library's %s"
                    % (arcname, kind))

    def test_only_existing_family_files_are_packed(self):
        from amaze.core import packages
        model = self.panel.material_model
        asset = self._material_with_files()
        item = packages.collect_asset(model, asset.mat_id)
        for kind, path in model.asset_files(asset.mat_id).items():
            if os.path.exists(path):
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


if __name__ == "__main__":
    unittest.main()
