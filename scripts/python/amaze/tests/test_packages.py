"""Packages: one test per requirement in docs/requirements/packages.md."""

import json
import os
import runpy
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

from amaze import messages  # noqa: E402
from amaze.core import (addons, asset_record, category, gradient_library, guard, library,  # noqa: E402
                        library_db, matx_sources, notes, packages, texstore)
from amaze.helpers import hostos  # noqa: E402
from amaze.tests import faults, test_support  # noqa: E402

PICTURE = "$AMAZEASSET/comments/" + "a" * 32 + ".png"
TEXTURE = "$AMAZEASSET/textures/brick.png"
TOOL = os.path.join(os.path.dirname(__file__), *[os.pardir] * 4, "tools",
                    "build-default-packages.py")


def read(path) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def brick(n=1, **record) -> tuple:
    """A material entry as a 3.0 export writes it, with a texture and a pasted picture."""
    mid, at = "%032x" % n, "assets/material/%032x/" % n
    entry = {"type": "asset", "section": "material", "id": mid,
             "record": dict({"id": mid, "name": "Brick %d" % n, "categories": ["Walls"],
                             "textures": [TEXTURE], "made_by_a_newer_amaze": "kept"}, **record),
             "note": {"items": [{"t": "text", "text": "rough"}, {"t": "image", "src": PICTURE}]},
             "files": {"mat": at + mid + ".mat"}, "textures": {TEXTURE: at + "textures/0_b.png"},
             "comment_pictures": {PICTURE: at + "comments/p.png"}}
    return entry, {at + mid + ".mat": b"nodes %d" % n, at + "textures/0_b.png": b"brick texture",
                   at + "comments/p.png": b"pasted picture"}


def palette(n, curated="") -> tuple:
    """A Colors entry, its record inline; `curated` is its preset mark."""
    record = {"id": "%032x" % n, "name": "Palette %d" % n, "categories": ["Mine"],
              "colors": [{"hex": "#101010"}]}
    return {"type": "asset", "section": "gradient", "id": "%032x" % n,
            "record": dict(record, **({"curated": curated} if curated else {}))}, {}


class _Library(unittest.TestCase):
    """A copy of the fixture library with its user, and its Materials and Colors models."""

    def setUp(self):
        self.out = tempfile.mkdtemp(prefix="amaze_packages_")
        self.addCleanup(shutil.rmtree, self.out, True)
        self.fresh()

    def fresh(self) -> None:
        """A new copy of the library, and models over it."""
        self.prefs = test_support.fixture_prefs(self)
        self.lib = self.prefs.dir.rstrip("/")
        self.addCleanup(library_db.release, self.prefs)
        self.models = {"material": library.MaterialLibrary(self.prefs),
                       "gradient": gradient_library.GradientLibrary(self.prefs)}
        self.categories = {"material": category.Categories(self.prefs),
                           "gradient": gradient_library.GradientCategories(self.prefs)}

    def package(self, *made, manifest=None, name="p.amazepkg") -> str:
        """A package of `(entry, members)` pairs; `manifest`: its own, raw bytes, or False for none."""
        path = os.path.join(self.out, name)
        manifest = manifest if manifest is not None else {
            "format": packages.FORMAT, "entries": [entry for entry, _m in made]}
        with zipfile.ZipFile(path, "w") as bundle:
            if manifest is not False:
                bundle.writestr(packages.MANIFEST, manifest if isinstance(manifest, bytes)
                                else json.dumps(manifest))
            for _entry, members in made:
                for arc, data in members.items():
                    bundle.writestr(arc, data)
        return path

    def bring(self, path, restore=False) -> dict:
        return packages.import_package(self.models, self.categories, self.prefs, path, restore)

    def state(self) -> dict:
        return test_support.library_state(self.lib)

    def rows(self, name) -> list:
        """The ids of the rows named `name` in the Materials database on disk."""
        found = guard.Guard(self.lib).read("materials.json").document or {}
        return [key for key, row in found.get("assets", {}).items() if row.get("name") == name]

    def folders(self, name, files=True) -> list:
        """The files under every folder of `name` in `materials/`, scratch files left out."""
        base = os.path.join(self.lib, "materials")
        found = [folder for folder in os.listdir(base) if folder.startswith(name + "__")]
        return found if not files else sorted(
            os.path.relpath(os.path.join(here, file), base).replace(os.sep, "/")
            for folder in found for here, _dirs, names in os.walk(os.path.join(base, folder))
            for file in names if not file.endswith(guard.SCRATCH))


class PackageTest(_Library):

    def test_pk01_an_import_never_writes_over_a_file_in_the_library(self):
        test_support.put(self.lib, "import/notes.txt", "the user's own")
        plain = {"type": "file", "kind": "text", "name": "notes.txt", "arc": "files/0_notes.txt"}
        path = self.package(brick(), (plain, {"files/0_notes.txt": b"from the package"}))
        before = self.state()
        self.bring(path)
        self.bring(path)
        after = self.state()
        self.assertEqual({}, {name: data for name, data in before.items() if after[name] != data
                              and not name.endswith(".json") and "backup/" not in name})
        self.assertEqual(2, len({name.split("/")[1] for name in after
                                 if name.startswith("materials/Brick 1__")}))
        self.assertEqual(2, sum(data == b"from the package" for name, data in after.items()
                                if name.startswith("import/")))

    def test_pk02_an_import_writes_only_into_its_new_folders_and_import(self):
        escaping, members = brick(2, textures=["$AMAZEASSET/../../x.png"])
        escaping["textures"] = {"$AMAZEASSET/../../x.png": list(members)[1]}
        before = self.state()
        summary = self.bring(self.package(brick(), (escaping, members)))
        self.assertEqual((1, 1), (summary["imported"], summary["refused"]))
        changed = [name for name, data in self.state().items() if before.get(name) != data
                   and not name.endswith(".json") and not name.startswith("backup/")]
        new = {name.split("/")[1] for name in changed if name.startswith("materials/Brick 1__")}
        self.assertEqual(1, len(new))
        own = "materials/%s/" % new.pop()
        self.assertEqual([], [name for name in changed if not name.startswith((own, "import/"))])
        self.assertEqual([], self.folders("Brick 2"))

    def attempt(self, package, disk) -> tuple:
        """Import into a new library over `disk`, then open it again: its rows, files and folders."""
        self.fresh()
        with mock.patch.object(library_db.guard_of(self.prefs), "disk", disk or guard.Disk()):
            try:
                self.bring(package)
            except faults.Cut:
                pass
        guard.Guard(self.lib).recover()    # what the next open does
        return self.rows("Brick 1"), self.folders("Brick 1"), self.folders("Brick 1", False)

    def test_pk03_each_asset_arrives_whole_or_not_at_all(self):
        def whole(rid):
            return sorted("Brick 1__%s/%s" % (rid, part) for part in (
                rid + ".mat", rid + ".json", "textures/brick.png", "comments/" + PICTURE[21:]))

        path = self.package(brick())
        damaged = test_support.put(self.out, "damaged.amazepkg", read(path).replace(
            b"brick texture", b"brick textur!"))
        counting = faults.FaultDisk()
        rows, files, _folders = self.attempt(path, counting)
        self.assertEqual(whole(rows[0]), files)
        for where, disk, package in (("full disk", faults.FaultDisk(full_from=1), path),
                                     ("a member that does not read back whole", None, damaged)):
            with self.subTest(where):
                self.assertEqual(([], [], []), self.attempt(package, disk))
        for step in range(1, counting.steps + 1):
            with self.subTest(crash_at=step):
                rows, files, _folders = self.attempt(path, faults.FaultDisk(cut_at=step))
                self.assertEqual(whole(rows[0]) if rows else [], files, "it arrived in part")

    def test_pk04_a_package_that_cannot_be_read_whole_changes_nothing(self):
        entry, members = brick()
        manifest = {"format": packages.FORMAT, "entries": [entry]}
        cases = {
            "damaged zip": test_support.put(self.out, "junk.amazepkg", b"PK\x03\x04 junk"),
            "no manifest": self.package((entry, members), manifest=False, name="none.amazepkg"),
            "unreadable manifest": self.package(name="bad.amazepkg", manifest=b"{not json"),
            "misshapen entry": self.package(brick(), (dict(entry, record="text"), {}),
                                            name="shape.amazepkg"),
            "missing member": self.package((entry, {}), name="missing.amazepkg"),
            "newer format": self.package(manifest=dict(manifest, format=99), name="new.amazepkg"),
            "an add-on": self.package(manifest=dict(manifest, kind="houdini-package"),
                                      name="addon.amazepkg"),
        }
        before = self.state()
        for name, path in cases.items():
            with self.subTest(name), self.assertRaises(packages.PackageError) as caught:
                self.bring(path)
            self.assertTrue(str(caught.exception))
        with self.subTest("over 16 GB"), mock.patch.object(packages, "MAX_UNPACKED_BYTES", 10), \
                self.assertRaises(packages.PackageError):
            self.bring(self.package(brick(), name="big.amazepkg"))
        self.assertEqual(before, self.state(), "a refused package changed the library")

    def test_pk05_an_export_changes_nothing_and_is_written_whole_or_not_at_all(self):
        model = self.models["material"]
        asset = next(a for a in model.assets if os.path.isfile(model.asset_files(a.mat_id)["mat"]))
        before = self.state()
        out = os.path.join(self.out, "export.amazepkg")
        item = packages.collect_asset(model, asset.mat_id)
        self.assertEqual(1, packages.write_package(out, [dict(item)]))
        self.assertEqual(before, self.state(), "an export changed the library")
        written = read(out)
        gone = dict(item, sources=dict(item["sources"], mat=os.path.join(self.out, "gone.mat")))
        with self.assertRaises(OSError):
            packages.write_package(out, [gone])
        self.assertEqual(written, read(out), "a failed export changed the old one")
        self.assertEqual(["export.amazepkg"], os.listdir(self.out), "a scratch file was left")

    def test_pk10_an_import_is_never_saved_over_another_asset(self):
        model = self.models["material"]
        taken = next(a for a in model.assets if a.mat_id and a.mat_id != "-1")
        before = test_support.asset_ids(model)
        path = self.package(brick(1, id=str(taken.mat_id)))
        self.bring(path)
        self.bring(path)
        arrived = test_support.arrived(model, before)
        self.assertEqual(2, len(arrived), "a package imported twice gave no second copy")
        self.assertNotIn(str(taken.mat_id), [str(a.mat_id) for a in arrived])
        self.assertEqual(taken.name, model.assets[model.find_asset_row_by_id(taken.mat_id)].name)

    def test_pk11_an_import_never_freezes_houdini(self):
        entry, members = brick()
        members[entry["files"]["mat"]] = os.urandom(300 * 1024)    # more than the first block read
        path = self.package((entry, members))
        url = "https://example.invalid/packages/store/p.amazepkg"
        test_support.serve(self, test_support.ranges_of(read(path)))
        source = matx_sources.AmazeSource()
        shared = source._open_package(url)
        steps, reads, real_read = [], [], zipfile.ZipFile.read
        bundle = source.import_reader(url, notify=lambda done, total: steps.append(done / total))
        self.assertIsNot(shared.fp, bundle.fp, "the import shares the previews' reader")
        with mock.patch.object(zipfile.ZipFile, "read", lambda zf, name, pwd=None: reads.append(
                getattr(name, "filename", name)) or real_read(zf, name, pwd)):
            summary = packages.import_entries(self.models, self.categories, self.prefs, bundle,
                                              [entry])
        self.assertEqual(1, summary["imported"])
        self.assertGreater(len(steps), 0, "no progress was shown")
        self.assertEqual(sorted(steps), steps)
        self.assertEqual([], reads, "a member was read whole into memory")

    def test_pk12_restore_replaces_only_the_copies_with_the_same_mark(self):
        model = self.models["gradient"]
        before = test_support.asset_ids(model)
        self.bring(self.package(palette(1, "wada/a"), palette(2, "wada/a"), palette(3)))
        old = {a.name: str(a.mat_id) for a in test_support.arrived(model, before)}
        summary = self.bring(self.package(palette(4, "wada/a"), name="r.amazepkg"), restore=True)
        self.assertEqual((1, 2), (summary["imported"], summary["replaced"]))
        now = {a.name: str(a.mat_id) for a in test_support.arrived(model, before)}
        self.assertEqual({"Palette 3", "Palette 4"}, set(now))
        self.assertEqual(old["Palette 3"], now["Palette 3"], "an unmarked asset was touched")
        self.assertNotIn(now["Palette 4"], ("%032x" % 4, old["Palette 1"], old["Palette 2"]))

    def exported(self) -> tuple:
        """Brick 1 with all it can hold, a lost texture too, exported: entry, members, builder, said."""
        model, gone = self.models["material"], "$AMAZEASSET/textures/gone.png"
        before = test_support.asset_ids(model)
        self.bring(self.package(brick(textures=[TEXTURE, gone])))
        asset, = test_support.arrived(model, before)
        files = model.asset_files(asset.mat_id)
        for kind, data in (("cop", b"cop network"), ("thumbnail", b"picture")):
            test_support.put(os.path.dirname(files[kind]), os.path.basename(files[kind]), data)
        builder = asset_record.builder_section({"type": "subnet", "interface": "controls",
                                                "values": {"rough": 0.5}})
        test_support.write_section(files["json"], asset_record.BUILDER, builder)
        out = os.path.join(self.out, "export.amazepkg")
        with test_support.captured_log() as log:
            self.assertEqual(1, packages.write_package(out, [packages.collect_asset(
                model, asset.mat_id)]))
        with zipfile.ZipFile(out) as bundle:
            entry, = json.loads(bundle.read(packages.MANIFEST))["entries"]
            members = {arc: bundle.read(arc) for arc in bundle.namelist()}
        return entry, members, builder, log.messages("refuse")

    def test_pk20_an_export_carries_the_whole_asset_and_its_record_lists_what_it_packs(self):
        entry, members, builder, _said = self.exported()
        files = {kind: members[arc] for kind, arc in entry["files"].items()}
        self.assertEqual(("Brick 1", [TEXTURE], [TEXTURE]), (
            entry["record"]["name"], entry["record"]["textures"], list(entry["textures"])))
        self.assertEqual((b"nodes 1", b"cop network", b"picture", b"brick texture"), (
            files["mat"], files["cop"], files["thumbnail"], members[entry["textures"][TEXTURE]]))
        self.assertEqual(builder, asset_record.builder_section(
            json.loads(files["json"])[asset_record.BUILDER]))
        self.assertEqual((["rough", PICTURE], b"pasted picture"), (
            [item.get("text") or item.get("src") for item in entry["note"]["items"]],
            members[entry["comment_pictures"][PICTURE]]))

    def test_pk21_an_export_names_a_texture_it_cannot_find(self):
        _entry, _members, _builder, said = self.exported()
        self.assertEqual([messages.PACKAGE_TEXTURES_NOT_FOUND % "gone.png (Brick 1)"], said)

    def test_pk22_an_imported_asset_is_new_in_import_with_every_field(self):
        model = self.models["material"]
        before = test_support.asset_ids(model)
        self.bring(self.package(brick()))
        asset, = test_support.arrived(model, before)
        record = asset.get_as_dict()
        self.assertNotEqual("%032x" % 1, str(asset.mat_id))
        self.assertEqual("kept", record["made_by_a_newer_amaze"])
        self.assertEqual(["Brick 1__%s" % asset.mat_id],
                         sorted({name.split("/")[0] for name in self.folders("Brick 1")}))

    def test_pk23_an_imported_asset_keeps_its_comments_and_their_pictures(self):
        model = self.models["material"]
        before = test_support.asset_ids(model)
        self.bring(self.package(brick()))
        asset, = test_support.arrived(model, before)
        key = notes.note_key("material", asset.mat_id)
        items = notes.note_for(self.prefs, key)["items"]
        self.assertEqual(["rough", PICTURE], [i.get("text") or i.get("src") for i in items])
        with open(notes.image_path(self.lib, key, PICTURE), "rb") as handle:
            self.assertEqual(b"pasted picture", handle.read())

    def test_pk24_a_package_from_an_older_amaze_imports_the_same_way(self):
        entry, members = brick()
        old = "$AMAZELIB/matX/brick/b.png"    # a texture where 2.0 kept it
        builder = {"type": "subnet", "dialog_script": "controls", "values": {"rough": 0.5}}
        entry["record"]["textures"] = [old]
        entry.update(textures={old: "t"}, files=dict(entry["files"], builder="b", capture="c"))
        members.update(t=b"old texture", b=json.dumps(builder).encode(), c=b"old picture")
        model = self.models["material"]
        before = test_support.asset_ids(model)
        self.bring(self.package((entry, members)))
        asset, = test_support.arrived(model, before)
        files = model.asset_files(asset.mat_id)
        with open(texstore.resolve(old, self.prefs, os.path.dirname(files["mat"])), "rb") as handle:
            self.assertEqual(b"old texture", handle.read(), "not where LS-38 reads it")
        self.assertEqual({"type": "subnet", "interface": "controls", "values": {"rough": 0.5}},
                         asset_record.saved_builder(self.prefs, asset.mat_id, model.DB_FILENAME))
        self.assertFalse(os.path.exists(files["thumbnail"]), "the old tile picture was brought in")

    def test_pk26_an_asset_that_fails_is_refused_alone(self):
        broken, members = brick(2)
        broken["files"] = {"mat": "assets/elsewhere.mat"}
        members["assets/elsewhere.mat"] = b"x"
        broken["textures"] = {"not a texture of its own": list(members)[1]}
        summary = self.bring(self.package(brick(), (broken, members)))
        self.assertEqual((1, 1), (summary["imported"], summary["refused"]))
        self.assertEqual(1, len(summary["problems"]))

    def test_pk27_the_user_is_told_which_comments_were_not_written(self):
        with mock.patch.object(notes, "set_notes", return_value=False):
            summary = self.bring(self.package(brick()))
        self.assertEqual(1, summary["imported"])
        self.assertIn(messages.PACKAGE_COMMENTS_NOT_WRITTEN % "Brick 1", summary["problems"])

    def test_pk28_an_amaze_that_cannot_read_a_packages_textures_refuses_it_as_too_new(self):
        self.exported()
        before = self.state()
        with mock.patch.object(packages, "FORMAT", 4), \
                self.assertRaises(packages.PackageError):    # an Amaze before 2.0.6 reads up to 4
            self.bring(os.path.join(self.out, "export.amazepkg"))
        self.assertEqual(before, self.state(), "a part of it was imported")
        self.assertEqual(4, addons.FORMAT, "an add-on package is no longer one every Amaze reads")

    def test_pk31_an_export_names_categories_and_an_import_finds_them_by_name(self):
        model, materials = self.models["material"], self.categories["material"]
        before, walls = test_support.asset_ids(model), materials.check_add_category("walls")
        count = len(materials.top_keys())
        self.bring(self.package(brick(1)))    # its package names Walls
        self.bring(self.package(brick(2), name="q.amazepkg"))
        one, two = test_support.arrived(model, before)
        self.assertEqual(([walls], [walls], count), (one.categories, two.categories,
                                                     len(materials.top_keys())))
        self.assertEqual(["walls"], packages.collect_asset(model, one.mat_id)["record"][
            "categories"], "an export names the category")
        self.bring(self.package(brick(3, categories=["Floors"]), name="f.amazepkg"))
        three, = test_support.arrived(model, before | {one.mat_id, two.mat_id})
        self.assertEqual((["Floors"], count + 1), (model.named_categories(three),
                                                   len(materials.top_keys())))
        palettes = self.models["gradient"]
        mine = self.categories["gradient"].check_add_category("mine")
        before = test_support.asset_ids(palettes)
        self.bring(self.package(palette(3, "wada/a"), name="r.amazepkg"), restore=True)
        restored, = test_support.arrived(palettes, before)
        self.assertEqual([mine], restored.categories, "a restored preset made a second Mine")

    def test_pk30_amazes_own_packages_carry_only_marked_assets(self):
        self.assertEqual(["Palette 2"], packages.unmarked([palette(1, "wada/a")[0],
                                                           palette(2)[0], brick()[0] | {
                                                               "record": {"curated": "x/y"}}]))
        out = os.path.join(self.out, "store")
        seed = gradient_library.GradientLibrary.seed_curated_palettes

        def one_unmarked(model, categories):
            seed(model, categories)
            model.assets[0]._extra.pop("curated", None)

        for sabotage, code, wrote in ((None, 0, True), (one_unmarked, 1, False)):
            shutil.rmtree(out, True)
            with self.subTest(unmarked=bool(sabotage)), \
                    mock.patch.object(sys, "argv", [TOOL, out]), \
                    mock.patch.object(gradient_library.GradientLibrary, "seed_curated_palettes",
                                      sabotage or seed), \
                    self.assertRaises(SystemExit) as ended:
                runpy.run_path(TOOL, run_name="__main__")
            self.assertEqual(code, ended.exception.code)
            self.assertEqual(wrote, bool(os.path.isdir(out) and os.listdir(out)))


class InThePaneTest(unittest.TestCase):
    """Export and import as a pane on a fixture library runs them."""

    def setUp(self):
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.pane = test_support.fixture_pane(self)
        self.out = test_support.scratch_dir("amaze_packages_")
        self.addCleanup(shutil.rmtree, self.out, True)

    def packed(self, export, *args) -> list:
        """The entries of the package `export(*args, path)` writes."""
        path = os.path.join(self.out, "%d.amazepkg" % len(os.listdir(self.out)))
        export(*args, path)
        with zipfile.ZipFile(path) as bundle:
            self.bundle = {arc: bundle.read(arc) for arc in bundle.namelist()}
            return json.loads(self.bundle[packages.MANIFEST])["entries"]

    def test_pk25_a_plain_file_goes_into_import_numbered_and_its_location_keeps_a_users_name(self):
        plain = {"type": "file", "kind": "text", "name": "notes.txt", "arc": "files/0_notes.txt"}
        path = os.path.join(self.out, "plain.amazepkg")
        with zipfile.ZipFile(path, "w") as bundle:
            bundle.writestr(packages.MANIFEST, json.dumps({"format": packages.FORMAT,
                                                           "entries": [plain]}))
            bundle.writestr(plain["arc"], b"from the package")
        folder = os.path.join(self.pane.prefs.dir, "import")
        key = hostos.canonical_path_key(folder)
        for _time in range(2):
            self.pane.package_import.import_file(path)
        listed = [hostos.canonical_path_key(one) for one in self.pane.prefs.file_folders]
        self.assertEqual((["notes.txt", "notes_1.txt"], True, "Import"), (
            sorted(os.listdir(folder)), key in listed,
            self.pane.prefs.file_folder_names.get(key)))
        self.assertIsNotNone(self.pane.file_folders_model.row_of(key), "not in the File sidebar")
        self.pane.prefs.set_file_folder_name(key, "Packages")
        self.pane.package_import.import_file(path)
        self.assertEqual("Packages", self.pane.prefs.file_folder_names.get(key))

    def test_pk29_each_export_packs_what_was_picked(self):
        materials = self.pane.sections["material"]
        model, proxy = self.pane.material_model, self.pane.material_sorted_model
        picked = [proxy.index(row, 0) for row in (0, 2)]
        self.assertEqual([proxy.mapToSource(index).data(model.IdRole) for index in picked],
                         [entry["id"] for entry in self.packed(materials.export_package_to, picked)])
        key = next(key for asset in model.assets for key in asset.categories)
        self.assertEqual(sorted(str(a.mat_id) for a in model.assets if key in a.categories),
                         sorted(e["id"] for e in self.packed(materials.export_category_to, key)))
        self.assertEqual(sorted(str(a.mat_id) for a in model.assets),
                         sorted(e["id"] for e in self.packed(materials.export_category_to, None)))
        files = self.pane.file_files_model
        files.set_folder(self.pane.prefs.file_folders[0])
        rows = [files.index(row, 0) for row in range(min(2, files.rowCount()))]
        entries = self.packed(self.pane.sections["file"].export_package_to, rows)
        wanted = []
        for index in rows:
            with open(index.data(files.PathRole), "rb") as handle:
                wanted.append((index.data(files.KindRole), handle.read()))
        self.assertEqual(wanted, [(entry["kind"], self.bundle[entry["arc"]]) for entry in entries])

if __name__ == "__main__":
    unittest.main()
