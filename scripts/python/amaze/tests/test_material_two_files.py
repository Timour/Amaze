"""Format 4: an asset is `<section>/<id>.mat|.json|.png`; format 3 is the converter's alone."""
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
from amaze.core import library_policy, material, repair, versions  # noqa: E402
from amaze.prefs import prefs as prefs_mod  # noqa: E402
from amaze.tests import test_support  # noqa: E402

MATERIALS, NODES = library_files.MATERIALS, library_files.NODES
ROW = {"id": "", "name": "Brick", "categories": ["Walls"], "tags": ["red"],
       "renderer": "Redshift", "date": "2026-01-01 00:00:00", "usd": 1}
OLD_BUILDER = {"format": 1, "type": "rs_usd_material_builder",
               "dialog_script": "{ name parms }", "values": {"tabmenumask": {"str": "rs"}}}
CONVERTED_BUILDER = {"type": "rs_usd_material_builder", "interface": "{ name parms }",
                     "values": {"tabmenumask": {"str": "rs"}}}
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


def library_version(directory: str) -> int:
    """The library version: in DataBase.json once converted, else in the old policy file."""
    reading = guard.Guard(directory).read(library_files.MASTER)
    entry = ((reading.document or {}).get("policy") or {}).get("library") or {}
    if isinstance(entry, dict) and entry.get("version"):
        return int(entry["version"])
    return library_conversion.old_version(directory)


def trashed(directory: str) -> int:
    """How many files the library trash holds."""
    return guard.Guard(directory).trash_held()["files"]


class _Interrupt(Exception):
    """A crash between writing an asset's new files and deleting its old ones."""


class _Library(unittest.TestCase):
    """A fixture copy, preferences that name it, and format 3 shapes laid as converter input."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.dir = self.prefs.dir
        self.old = os.path.join(self.dir, "mat")
        self.materials = material.section_folder(self.dir, MATERIALS)
        self.nodes = material.section_folder(self.dir, NODES)

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

    def rows(self, filename: str) -> dict:
        """The rows of an old section database, from its 2.0 database once that is written."""
        new = library_conversion.OLD_SECTIONS.get(filename, (filename,))[0]
        for path in (self.at(new), self.at(filename)):
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8-sig") as handle:
                held = json.load(handle).get("assets")
            if isinstance(held, dict):
                return {str(key): row for key, row in held.items()}
            if path == self.at(filename):
                return {str(row.get("id")): row for row in held}
        return {}

    def old_asset(self, asset_id: str, folder=None, builder=True, stamp=True) -> list:
        """A format 3 asset: `.mat`, `.interface`, as asked its sidecar and its stamp."""
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

    def record(self, asset_id: str, section: str = MATERIALS) -> dict:
        return asset_record.read(asset_record.path_for(self.prefs, asset_id, section))

    def metadata(self, asset_id: str, **changed) -> None:
        asset_record.write_section(asset_record.path_for(self.prefs, asset_id, MATERIALS),
                                   asset_record.METADATA, dict(ROW, id=asset_id, **changed))

    def convert(self, **kwargs):
        asked = []
        outcome = library_conversion.convert(self.dir, lambda: asked.append(1) or True, **kwargs)
        return outcome, asked

    def mismatch_for(self, asset_id: str):
        """`asset_record.read` answering wrong for `asset_id`'s new file once it exists."""
        real = asset_record.read

        def reading(path):
            if os.path.basename(path) == asset_id + ".json" and os.path.exists(path):
                return {"metadata": {"name": "not what was written"}, "builder": {}}
            return real(path)
        return mock.patch.object(asset_record, "read", reading)


class _OldLibrary(_Library):
    """An older library laid out from nothing: its root files, `mat/`, `img/`, `captures/`."""

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
        self.nodes = material.section_folder(self.dir, NODES)
        write(self.at(library_conversion.OLD_POLICY),
              {"library_version": library_policy.LIBRARY_VERSION - 1})
        os.makedirs(self.old)


class AFullConversionTest(_OldLibrary):
    """A small format 3 library converted whole: every shape lands, nothing old is left."""

    def lay_out(self):
        self.database("library.json", ["MAT1", "BOTH1", "NOMAT1"])
        self.database("cops.json", ["NODE1", "BOTH1"])
        self.database("code.json", ["CODE1"])
        self.database("gradients.json", ["COL1"])
        for one in ("MAT1", "NODE1", "BOTH1", "ORPHAN1"):
            self.old_asset(one)
        self.old_asset("SIDE1", self.materials, stamp=False)    # beside its section's files
        self.database("library.json", ["SIDE1"])
        write(os.path.join(self.old, "NOMAT1.interface"), INTERFACE)    # listed, no .mat at all
        write(os.path.join(self.old, "CODE1.stamp.json"), dict(ROW, id="CODE1"))
        write(os.path.join(self.old, "COL1.stamp.json"), dict(ROW, id="COL1"))
        self.old_pictures("MAT1")
        self.old_pictures("CODE1")
        folder = os.path.join(self.old, "versions", "MAT1")
        write(os.path.join(folder, "1.mat"), "version one\n")
        write(os.path.join(folder, "1.builder.json"), OLD_BUILDER)
        write(os.path.join(folder, "1.interface"), INTERFACE)
        write(os.path.join(folder, "versions.json"),
              {"active": 1, "versions": [{"n": 1, "name": "V1", "file": "1"}]})
        nodes_versions = os.path.join(self.nodes, "versions", "NODE1")
        write(os.path.join(nodes_versions, "2.mat"), "node version two\n")
        write(os.path.join(nodes_versions, "2.interface"), INTERFACE)

    def test_every_shape_lands_in_format_4(self):
        self.lay_out()
        fixture = {name: data for name, data in listing(self.materials).items()
                   if name.startswith("1398")}
        self.assertTrue(library_conversion.needs_conversion(self.dir))
        outcome, asked = self.convert()
        self.assertEqual(library_conversion.DONE, outcome.status)
        self.assertEqual([1], asked, "confirm() was not asked exactly once")
        self.assertEqual(library_policy.LIBRARY_VERSION, library_version(self.dir))
        self.assertFalse(library_conversion.needs_conversion(self.dir))

        mat1 = self.record("MAT1")
        self.assertEqual(CONVERTED_BUILDER, mat1["builder"])
        self.assertEqual(self.rows("library.json")["MAT1"], mat1["metadata"],
                         "the metadata is not the database's row")
        self.assertEqual("nodes of MAT1\n", read_bytes(os.path.join(
            self.materials, "MAT1.mat")).decode())
        self.assertEqual(b"render MAT1", read_bytes(os.path.join(self.materials, "MAT1.png")),
                         "a tile with no stored face did not keep its render")
        self.assertEqual("rs_usd_material_builder", self.record("NODE1", NODES)["builder"]["type"])
        self.assertTrue(os.path.exists(os.path.join(self.nodes, "NODE1.mat")))
        self.assertEqual("rs_usd_material_builder", self.record("SIDE1")["builder"]["type"])
        orphan = self.record("ORPHAN1")
        self.assertTrue(os.path.exists(os.path.join(self.materials, "ORPHAN1.mat")),
                        "an orphaned asset did not go to materials/")
        self.assertEqual("Stamped ORPHAN1", orphan["metadata"].get("name"),
                         "an orphan's stamp did not become its metadata")
        for kept in ("BOTH1.mat", "BOTH1.interface", "BOTH1.builder.json", "BOTH1.stamp.json"):
            self.assertTrue(os.path.exists(os.path.join(self.old, kept)),
                            "an id two databases name was moved: %s" % kept)
        self.assertFalse(os.path.exists(os.path.join(self.materials, "BOTH1.mat")))
        self.assertFalse(os.path.exists(os.path.join(self.nodes, "BOTH1.mat")))

        moved = os.path.join(self.materials, "versions", "MAT1")
        self.assertEqual(["MAT1_1.json", "MAT1_1.mat", "versions.json"],
                         sorted(os.listdir(moved)))
        archive = asset_record.read(os.path.join(moved, "MAT1_1.json"))
        self.assertEqual(CONVERTED_BUILDER, archive["builder"])
        self.assertEqual({}, archive["metadata"], "a version archived metadata")
        self.assertEqual("rs_usd_material_builder", asset_record.read(os.path.join(
            self.nodes, "versions", "NODE1", "NODE1_2.json"))["builder"]["type"])
        self.assertFalse(os.path.exists(os.path.join(self.nodes, "versions", "NODE1",
                                                     "2.interface")))

        self.assertFalse(os.path.exists(self.at("code", "CODE1.png")),
                         "Code kept a render it paints itself")
        self.assertEqual(sorted(["BOTH1.builder.json", "BOTH1.interface", "BOTH1.mat",
                                 "BOTH1.stamp.json", "NOMAT1.interface"]),
                         sorted(os.listdir(self.old)),
                         "mat/ holds more than the id two sections name and the set-aside one")
        self.assertFalse(os.path.exists(self.at("captures")), "an emptied captures/ stayed")
        left_in_img = sorted(os.listdir(self.at("img"))) if os.path.isdir(self.at("img")) else []
        self.assertEqual([], [name for name in left_in_img if name.endswith(".png")],
                         "a format 3 picture or _icon.png stayed in img/")
        for name in ("SIDE1.interface", "SIDE1.builder.json"):
            self.assertFalse(os.path.exists(os.path.join(self.materials, name)), name)

        self.assertEqual(["NOMAT1"], [one.asset_id for one in outcome.set_aside],
                         "a listed asset with no .mat was not set aside alone")
        self.assertNotIn("NOMAT1", self.rows("library.json"))
        self.assertEqual(fixture, {name: data for name, data in listing(self.materials).items()
                                   if name.startswith("1398")},
                         "the conversion changed an asset that was format 4 already")

    def test_a_rerun_finds_nothing_to_do(self):
        self.database("library.json", ["MAT1"])
        self.database("gradients.json", ["COL1"])
        self.old_asset("MAT1")
        self.old_pictures("MAT1")
        self.assertEqual(library_conversion.DONE, self.convert()[0].status)
        before = listing(self.dir)
        outcome, asked = self.convert()
        self.assertEqual(library_conversion.NOTHING, outcome.status)
        self.assertEqual([], asked)
        self.assertEqual(before, listing(self.dir))

    def test_a_rerun_over_what_was_left_changes_nothing(self):
        """The files a run leaves in mat/ for the user: a second run moves and rewrites none."""
        self.lay_out()
        self.convert()
        before = listing(self.dir)
        self.convert()
        self.assertEqual(before, listing(self.dir))


class PicturesTest(_OldLibrary):
    """Each tile keeps the picture it showed: a stored Capture its capture, else its render."""

    def lay_out(self):
        self.database("library.json", ["SHOWCAP1", "SHOWREN1"])
        for one in ("SHOWCAP1", "SHOWREN1"):
            self.old_asset(one)
            self.old_pictures(one)

    def check(self):
        for one, shown in (("SHOWCAP1", b"capture SHOWCAP1"), ("SHOWREN1", b"render SHOWREN1")):
            self.assertEqual(shown, read_bytes(os.path.join(self.materials, one + ".png")),
                             "%s kept the wrong picture" % one)
            for old in ("img/%s.png", "captures/%s.png", "img/%s_icon.png"):
                self.assertFalse(os.path.exists(self.at(*(old % one).split("/"))), old % one)

    def icons(self, table: dict) -> str:
        """The old icons file as format 3 wrote it, raw: its table under the icons key."""
        return write(self.at("icons.json"), {"icons": table})

    def test_a_stored_capture_face_keeps_the_capture(self):
        """The choice raw in the old icons file; afterwards the tile shows as image."""
        from amaze.core import tile_icons
        self.lay_out()
        self.icons({"SHOWCAP1": {"face": "capture"}, "SHOWREN1": {"face": "preview"}})
        outcome, _asked = self.convert()
        self.assertEqual(library_conversion.DONE, outcome.status)
        self.check()
        library_db.release()
        self.assertEqual("image", tile_icons.face_of(
            tile_icons.override_for(self.prefs, "SHOWCAP1", MATERIALS)),
            "the stored capture face does not read as image")

    def test_no_icons_json_keeps_every_render(self):
        """No stored choice at all: each tile keeps its render, the capture goes."""
        self.lay_out()
        outcome, _asked = self.convert()
        self.assertEqual(library_conversion.DONE, outcome.status)
        self.assertEqual(b"render SHOWCAP1",
                         read_bytes(os.path.join(self.materials, "SHOWCAP1.png")))

    def test_an_unreadable_icons_json_blocks_with_nothing_changed(self):
        """Converting past an unreadable old file would drop what it holds: nothing runs."""
        self.lay_out()
        write(self.at("icons.json"), "{broken")
        before = listing(self.dir)
        outcome, asked = self.convert()
        self.assertEqual(library_conversion.BLOCKED, outcome.status)
        self.assertIn("icons.json", outcome.why)
        self.assertEqual([], asked)
        self.assertEqual(before, listing(self.dir))


class AReadBackMismatchSetsTheAssetAsideTest(_OldLibrary):
    """A new file that does not read back as built: its asset is set aside, the rest converts."""

    def test_the_asset_s_old_files_stay_byte_identical_and_its_row_goes(self):
        self.database("library.json", ["GOOD1", "BAD1"], BAD1="Broken Brick")
        self.old_asset("GOOD1")
        bad = self.old_asset("BAD1") + self.old_pictures("BAD1")
        before = {path: read_bytes(path) for path in bad}
        with self.mismatch_for("BAD1"):
            outcome, _asked = self.convert()
        self.assertEqual(library_conversion.DONE, outcome.status)
        self.assertEqual(["BAD1"], [one.asset_id for one in outcome.set_aside])
        one = outcome.set_aside[0]
        self.assertEqual((MATERIALS, "Broken Brick"), (one.section, one.name))
        self.assertEqual(sorted(bad), sorted(one.files))
        for path, data in before.items():
            self.assertEqual(data, read_bytes(path), "%s changed" % path)
        for suffix in (".mat", ".json", ".png"):
            self.assertFalse(os.path.exists(os.path.join(self.materials, "BAD1" + suffix)),
                             "what the failed asset wrote was not undone: " + suffix)
        rows = self.rows("library.json")
        self.assertNotIn("BAD1", rows, "the set-aside row stayed in its database")
        self.assertIn("GOOD1", rows)
        self.assertEqual(CONVERTED_BUILDER, self.record("GOOD1")["builder"])
        self.assertFalse(os.path.exists(os.path.join(self.old, "GOOD1.mat")))
        self.assertEqual(library_policy.LIBRARY_VERSION, library_version(self.dir))

    def test_a_missing_mat_among_many_sets_that_one_aside(self):
        many = ["MANY%03d" % n for n in range(200)]
        self.database("library.json", many)
        for one in many:
            self.old_asset(one, builder=False, stamp=False)
        os.remove(os.path.join(self.old, "MANY007.mat"))
        outcome, _asked = self.convert()
        self.assertEqual(library_conversion.DONE, outcome.status)
        self.assertEqual(["MANY007"], [one.asset_id for one in outcome.set_aside])
        rows = self.rows("library.json")
        self.assertNotIn("MANY007", rows)
        self.assertEqual(199, len([one for one in many if one in rows]))
        self.assertTrue(os.path.exists(os.path.join(self.old, "MANY007.interface")))

    def test_a_picture_no_database_names_is_left_and_is_no_failed_asset(self):
        self.database("library.json", ["GOOD1"])
        self.old_asset("GOOD1")
        stray = self.old_pictures("GONE1")
        outcome, _asked = self.convert()
        self.assertEqual(library_conversion.DONE, outcome.status)
        self.assertEqual([], [one.asset_id for one in outcome.set_aside],
                         "a picture with no row and no .mat was reported as an asset")
        for path in stray:
            self.assertTrue(os.path.exists(path), "%s was removed" % path)
        self.assertIn("GOOD1", self.rows("library.json"))

    def test_trash_moves_exactly_the_set_aside_files(self):
        self.database("library.json", ["GOOD1", "BAD1"])
        self.old_asset("GOOD1")
        self.old_asset("BAD1")
        with self.mismatch_for("BAD1"):
            outcome, _asked = self.convert()
        files = outcome.set_aside[0].files
        held = trashed(self.dir)
        others = {path: data for path, data in listing(self.dir).items()
                  if os.path.join(self.dir, path) not in files}
        self.assertEqual(len(files), library_conversion.trash_set_aside(self.dir, outcome.set_aside))
        for path in files:
            self.assertFalse(os.path.exists(path), "%s was not moved to the trash" % path)
        self.assertEqual(held + len(files), trashed(self.dir))
        after = listing(self.dir)
        self.assertEqual(others, {path: data for path, data in after.items() if path in others},
                         "the trash took or changed a file that was not set aside")


class AnUnknownFileInMatStaysTest(_OldLibrary):

    def test_it_survives_with_its_folder(self):
        self.database("library.json", ["MAT1"])
        self.old_asset("MAT1")
        notes = write(os.path.join(self.old, "notes.txt"), "mine\n")
        outcome, _asked = self.convert()
        self.assertEqual(library_conversion.DONE, outcome.status)
        self.assertEqual(["notes.txt"], os.listdir(self.old))
        self.assertEqual(b"mine\n", read_bytes(notes))
        self.assertEqual(library_policy.LIBRARY_VERSION, library_version(self.dir))

    def test_the_backups_earlier_updates_left_go_and_the_folder_with_them(self):
        self.database("library.json", ["MAT1"])
        self.old_asset("MAT1")
        write(os.path.join(self.old, "MAT1.mat.pre-adopt"), "before the texture update\n")
        write(os.path.join(self.old, "GONE9.mat.pre-adopt"), "of an asset long deleted\n")
        kept = os.path.join(self.old, "backup-redshift-vopnet-2026-09-04")
        write(os.path.join(kept, "MAT1.mat"), "before the builder upgrade\n")
        write(os.path.join(kept, "MAT1.interface"), INTERFACE)
        outcome, _asked = self.convert()
        self.assertEqual(library_conversion.DONE, outcome.status)
        self.assertFalse(os.path.exists(self.old), "mat/ is still there: %s"
                         % (os.path.isdir(self.old) and sorted(os.listdir(self.old))))
        self.assertTrue(os.path.exists(os.path.join(self.materials, "MAT1.mat")))

    def test_a_folder_of_the_user_s_own_in_mat_stays(self):
        self.database("library.json", ["MAT1"])
        self.old_asset("MAT1")
        mine = write(os.path.join(self.old, "backup-mine", "keep.txt"), "mine\n")
        outcome, _asked = self.convert()
        self.assertEqual(library_conversion.DONE, outcome.status)
        self.assertEqual(b"mine\n", read_bytes(mine))


class AnInterruptedConversionRerunsTest(_OldLibrary):
    """Stopped after an asset's new files were written and before its old ones went."""

    def lay_out(self):
        self.database("library.json", ["RUN1", "RUN2"])
        self.database("cops.json", ["RUN3"])
        made = {one: self.old_asset(one) for one in ("RUN1", "RUN2")}
        made["RUN3"] = self.old_asset("RUN3")
        self.old_pictures("RUN1")
        return made

    def test_the_rerun_finishes_and_deletes_only_old_files(self):
        self.lay_out()
        fixture = {name: data for name, data in listing(self.materials).items()
                   if name.startswith("1398")}
        with mock.patch.object(library_conversion, "_remove", side_effect=_Interrupt):
            with self.assertRaises(_Interrupt):
                self.convert()
        self.assertTrue(os.path.exists(os.path.join(self.materials, "RUN1.json")),
                        "premise: the first asset's new files were written")
        self.assertTrue(os.path.exists(os.path.join(self.old, "RUN1.mat")),
                        "premise: its old files were not yet deleted")
        self.assertLess(library_version(self.dir), library_policy.LIBRARY_VERSION)
        self.assertTrue(library_conversion.needs_conversion(self.dir), "the mark was lost")
        outcome, _asked = self.convert()
        self.assertEqual(library_conversion.DONE, outcome.status)
        self.assertEqual([], outcome.set_aside, "a half-converted asset was set aside")
        for one, section, folder in (("RUN1", MATERIALS, self.materials),
                                     ("RUN2", MATERIALS, self.materials),
                                     ("RUN3", NODES, self.nodes)):
            self.assertEqual(CONVERTED_BUILDER, self.record(one, section)["builder"], one)
            self.assertEqual(b"nodes of " + one.encode() + b"\n",
                             read_bytes(os.path.join(folder, one + ".mat")))
        self.assertEqual(b"render RUN1", read_bytes(os.path.join(self.materials, "RUN1.png")))
        self.assertFalse(os.path.exists(self.old))
        self.assertEqual(fixture, {name: data for name, data in listing(self.materials).items()
                                   if name.startswith("1398")})

    def test_a_newer_file_already_in_place_is_kept(self):
        """Pre-created new files, as a crash or a later save leaves them: never overwritten."""
        self.lay_out()
        write(os.path.join(self.materials, "RUN1.mat"), "saved since\n")
        write(os.path.join(self.materials, "RUN1.png"), b"captured since")
        outcome, _asked = self.convert()
        self.assertEqual(library_conversion.DONE, outcome.status)
        self.assertEqual(b"saved since\n", read_bytes(os.path.join(self.materials, "RUN1.mat")))
        self.assertEqual(b"captured since", read_bytes(os.path.join(self.materials, "RUN1.png")))
        self.assertFalse(os.path.exists(os.path.join(self.old, "RUN1.mat")))


class NothingChangesUnlessItRunsTest(_OldLibrary):
    """Blocked, cancelled or opened headless: the library is byte for byte what it was."""

    def lay_out(self):
        self.database("library.json", ["MAT1"])
        self.database("cops.json", ["NODE1"])
        self.old_asset("MAT1")
        self.old_asset("NODE1")
        self.old_pictures("MAT1")
        return listing(self.dir)

    def test_a_corrupt_database_blocks_with_nothing_changed(self):
        self.lay_out()
        write(self.at("cops.json"), "{corrupt")
        before = listing(self.dir)
        outcome, asked = self.convert()
        self.assertEqual(library_conversion.BLOCKED, outcome.status)
        self.assertEqual("the %s database is corrupt/unreadable."
                         % library_files.section_label(NODES), outcome.why)
        self.assertNotIn(".json", outcome.why, "the reason names a file, not the database")
        self.assertEqual([], asked, "the box was shown for a conversion that cannot run")
        self.assertEqual(before, listing(self.dir), "a blocked conversion changed the library")
        self.assertTrue(library_conversion.needs_conversion(self.dir))

    def test_a_cancelled_conversion_touches_nothing(self):
        before = self.lay_out()
        policy = self.at(library_conversion.OLD_POLICY)
        policy_bytes = read_bytes(policy) if os.path.exists(policy) else None
        outcome = library_conversion.convert(self.dir, lambda: False)
        self.assertEqual(library_conversion.CANCELLED, outcome.status)
        self.assertEqual(before, listing(self.dir), "a cancelled conversion changed the library")
        self.assertEqual(policy_bytes, read_bytes(policy) if os.path.exists(policy) else None)
        self.assertTrue(library_conversion.needs_conversion(self.dir))

    def test_a_headless_open_never_converts(self):
        from amaze.actions import library as library_actions
        from amaze.panel import panel as panel_mod
        before = self.lay_out()
        holder = types.SimpleNamespace(prefs=self.prefs)
        with mock.patch.object(panel_mod, "hou", types.SimpleNamespace()):    # no hou.ui
            self.assertFalse(panel_mod.AmazePanel._converted(holder, self.dir))
        import hou
        if getattr(hou, "ui", None) is None:    # the real headless Houdini, as a script opens it
            self.assertFalse(panel_mod.AmazePanel._converted(holder, self.dir))
        library_actions.prepare(self.prefs)
        self.assertEqual(before, listing(self.dir), "opening headless changed the library")
        self.assertTrue(library_conversion.needs_conversion(self.dir))


class TheBoxesTest(_OldLibrary):
    """The panel's boxes, through `_converted` with a stand-in `hou.ui`."""

    def run_panel(self, answers):
        from amaze.panel import panel as panel_mod
        shown = []
        answers = list(answers)

        def display(text, **kwargs):
            shown.append((text, kwargs))
            return answers.pop(0) if answers else 0

        class Operation:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def updateProgress(self, _fraction):
                pass

        fake = types.SimpleNamespace(
            ui=types.SimpleNamespace(displayMessage=display),
            InterruptableOperation=Operation, OperationInterrupted=RuntimeError,
            severityType=types.SimpleNamespace(Warning="warning", Message="message"))
        holder = types.SimpleNamespace(prefs=self.prefs)
        holder._offer_old_trash = types.MethodType(panel_mod.AmazePanel._offer_old_trash, holder)
        with mock.patch.object(panel_mod, "hou", fake):
            opened = panel_mod.AmazePanel._converted(holder, self.dir)
        return opened, shown

    def test_a_cancelled_conversion_asks_nothing_about_the_user(self):
        from amaze.panel import panel as panel_mod
        self.database("library.json", ["MAT1"])
        self.old_asset("MAT1")
        shown, opened = [], []
        fake = types.SimpleNamespace(ui=types.SimpleNamespace(
            displayMessage=lambda text, **kwargs: shown.append(text) or 1))
        with mock.patch.object(panel_mod, "hou", fake):
            answer = panel_mod.AmazePanel.ensure_library_user(types.SimpleNamespace(
                prefs=self.prefs, set_library=lambda: opened.append(True)))
        self.assertEqual(("", [], []), (answer, shown, opened),
                         "a library left unconverted was asked about its user")
        holder = types.SimpleNamespace(prefs=self.prefs, open_library=lambda needs_user: False,
                                       set_library=lambda: opened.append(True))
        with mock.patch.object(panel_mod, "hou", fake):
            self.assertFalse(panel_mod.AmazePanel._open_at_start(holder))
        self.assertEqual([True], opened, "Preferences, where Apply converts it, did not open")

    def test_the_conversion_is_never_asked_inside_the_pane_s_build(self):
        import inspect
        from amaze.panel import panel as panel_mod
        build = inspect.getsource(panel_mod.AmazePanel._build)
        self.assertIn("library_conversion.needs_conversion(self.prefs.dir)", build)
        self.assertLess(build.index("needs_conversion"), build.index("_defer_open_library()"),
                        "a library to convert is opened inside the build, where its box holds the pane")

    def test_preferences_lists_the_older_library_s_users_and_nothing_is_written_to_it(self):
        from amaze.core import library_settings
        write(self.at("users.json"), {"users": {test_support.FIXTURE_USER: {"name": "Anna"}}})
        self.database("library.json", ["MAT1"])
        self.old_asset("MAT1")
        self.assertEqual({test_support.FIXTURE_USER: "Anna"},
                         library_conversion.old_users(self.dir))
        before = listing(self.dir)
        self.assertFalse(library_settings.takes_writes(self.prefs))
        self.prefs.rendersize = 512
        self.prefs.save()
        self.assertEqual(before, listing(self.dir),
                         "a save wrote into a library that is not converted yet")

    def test_the_assets_set_aside_are_named_and_move_to_trash_takes_them(self):
        self.database("library.json", ["GOOD1", "BAD1"], BAD1="Broken Brick")
        self.old_asset("GOOD1")
        bad = self.old_asset("BAD1")
        with self.mismatch_for("BAD1"):
            opened, shown = self.run_panel([0, 1])    # Convert, then Move to Trash
        self.assertTrue(opened)
        self.assertEqual(2, len(shown), [text for text, _k in shown])
        self.assertEqual(messages.CONFIRM_CONVERT_LIBRARY % library_policy.LIBRARY_VERSION_SINCE,
                         shown[0][0])
        self.assertEqual(messages.BUTTONS_CONVERT_LIBRARY, tuple(shown[0][1]["buttons"]))
        text, kwargs = shown[1]
        self.assertEqual(messages.CONVERT_LIBRARY_DONE_SOME_LEFT % "1 material", text)
        self.assertEqual("Broken Brick", kwargs.get("details"),
                         "the details do not name the asset")
        self.assertEqual(messages.BUTTONS_UNCONVERTED, tuple(kwargs["buttons"]))
        for path in bad:
            self.assertFalse(os.path.exists(path), "Move to Trash left %s" % path)

    def test_every_name_is_in_the_details_one_a_line(self):
        many = ["BAD%02d" % n for n in range(12)]
        self.database("library.json", many, **{one: "Name " + one for one in many})
        self.database("cops.json", ["NBAD1"], NBAD1="Node Name")
        for one in many:
            self.old_asset(one)
        self.old_asset("NBAD1")
        for one in many + ["NBAD1"]:
            os.remove(os.path.join(self.old, one + ".mat"))    # each one is set aside
        opened, shown = self.run_panel([0, 0])
        self.assertTrue(opened)
        text, kwargs = shown[1]
        self.assertEqual(messages.CONVERT_LIBRARY_DONE_SOME_LEFT % "12 materials and 1 node",
                         text)
        self.assertEqual(sorted(["Name " + one for one in many] + ["Node Name"]),
                         sorted(kwargs["details"].split("\n")))
        self.assertFalse(hasattr(messages, "AND_MORE"))

    def test_leave_keeps_the_files(self):
        self.database("library.json", ["BAD1"])
        bad = self.old_asset("BAD1")
        with self.mismatch_for("BAD1"):
            opened, _shown = self.run_panel([0, 0])    # Convert, then Leave
        self.assertTrue(opened)
        for path in bad:
            self.assertTrue(os.path.exists(path), "Leave moved %s" % path)

    def test_done_blocked_and_cancel(self):
        self.database("library.json", ["MAT1"])
        self.old_asset("MAT1")
        before = listing(self.dir)
        opened, shown = self.run_panel([1])    # Cancel
        self.assertFalse(opened, "a cancelled conversion opened the library")
        self.assertEqual(1, len(shown))
        self.assertEqual(before, listing(self.dir))
        write(self.at("cops.json"), "{corrupt")
        opened, shown = self.run_panel([])
        self.assertFalse(opened)
        self.assertEqual(1, len(shown))
        self.assertEqual(messages.CONVERT_LIBRARY_BLOCKED % (
            "the %s database is corrupt/unreadable." % library_files.section_label(NODES)),
            shown[0][0])
        write(self.at("cops.json"), {"format": 3, "categories": ["_All"], "tags": [],
                                     "assets": []})
        opened, shown = self.run_panel([0])
        self.assertTrue(opened)
        self.assertEqual(messages.CONVERT_LIBRARY_DONE, shown[-1][0])


class _Classic:
    """A stand-in for the Houdini side: is the renderer loaded, what the box answers, the rebuild."""

    def __init__(self, test, loaded=True, trash=True, fails=False) -> None:
        self.test, self.is_loaded, self.trash, self.fails = test, loaded, trash, fails
        self.asked, self.rebuilt = [], []

    def loaded(self, renderer) -> bool:
        return self.is_loaded

    def ask(self, count, renderer) -> bool:
        self.asked.append((count, renderer.label))
        return self.trash

    def rebuild(self, asset_id, name, renderer) -> None:
        if self.fails:
            raise RuntimeError("the node could not be made")
        self.rebuilt.append(asset_id)
        path = asset_record.path_for(self.test.prefs, asset_id, MATERIALS)
        asset_record.write_section(path, asset_record.BUILDER, dict(
            CONVERTED_BUILDER, type=renderer.usd_builder))


class AClassicMaterialIsRebuiltTest(_OldLibrary):
    """A Material saved in a classic container is rebuilt, trashed at the user's word, or set aside."""

    def setUp(self):
        super().setUp()
        self.database("library.json", ["USD1", "OLD1"], OLD1="Old Brick")
        self.old_asset("USD1")
        self.classic_files = self.old_asset("OLD1", stamp=False)
        write(os.path.join(self.old, "OLD1.builder.json"), dict(OLD_BUILDER, type="redshift_vopnet"))
        self.version = write(os.path.join(self.old, "versions", "OLD1", "1.mat"), "version one\n")
        write(os.path.join(self.old, "versions", "OLD1", "versions.json"),
              {"active": 1, "versions": [{"n": 1, "name": "V1", "file": "1"}]})

    def test_with_its_renderer_loaded_it_is_rebuilt_and_its_classic_versions_go(self):
        classic = _Classic(self)
        outcome, _asked = self.convert(classic=classic)
        self.assertEqual((library_conversion.DONE, []), (outcome.status, outcome.set_aside))
        self.assertEqual((["OLD1"], []), (classic.rebuilt, classic.asked))
        self.assertEqual("rs_usd_material_builder", self.record("OLD1")["builder"]["type"])
        self.assertEqual({"USD1", "OLD1"}, set(self.rows("library.json")))
        self.assertFalse(os.path.exists(os.path.join(self.materials, "versions", "OLD1")),
                         "a version only a classic container can load was kept")
        self.assertEqual(0, trashed(self.dir))

    def test_cancel_at_the_renderer_box_changes_nothing(self):
        before = listing(self.dir)
        classic = _Classic(self, loaded=False, trash=False)
        outcome, asked = self.convert(classic=classic)
        self.assertEqual(library_conversion.CANCELLED, outcome.status)
        self.assertEqual(([1], [(1, "Redshift")]), (asked, classic.asked))
        self.assertEqual(before, listing(self.dir))

    def test_move_to_trash_takes_them_out_and_converts_the_rest(self):
        classic = _Classic(self, loaded=False, trash=True)
        outcome, _asked = self.convert(classic=classic)
        self.assertEqual((library_conversion.DONE, []), (outcome.status, outcome.set_aside))
        self.assertEqual({"USD1"}, set(self.rows("library.json")))
        self.assertEqual([], classic.rebuilt)
        for path in self.classic_files + [self.version]:
            self.assertFalse(os.path.exists(path), "%s was left in the library" % path)
        self.assertGreaterEqual(trashed(self.dir), len(self.classic_files) + 1)
        self.assertFalse(os.path.exists(os.path.join(self.materials, "OLD1.mat")))

    def test_a_rebuild_that_fails_sets_the_material_aside(self):
        outcome, _asked = self.convert(classic=_Classic(self, fails=True))
        self.assertEqual(["Old Brick"], [one.name for one in outcome.set_aside])
        self.assertEqual({"USD1"}, set(self.rows("library.json")))
        self.assertTrue(all(os.path.exists(path) for path in outcome.set_aside[0].files))
        self.assertIn(os.path.join(self.materials, "OLD1.mat"), outcome.set_aside[0].files)
        self.assertTrue(os.path.exists(self.version), "a set-aside material lost its versions")

    def test_the_box_names_how_many_and_the_renderer(self):
        from amaze.render import classic_rebuild
        with mock.patch.object(classic_rebuild.Rebuilder, "loaded", lambda _self, _r: False):
            opened, shown = TheBoxesTest.run_panel(self, [0, 1])    # Convert, then Cancel
        self.assertFalse(opened)
        self.assertEqual(messages.CONVERT_CLASSIC_NEEDS_RENDERER % (
            "1 material", "Redshift", "Redshift"), shown[1][0])
        self.assertEqual(messages.BUTTONS_CLASSIC_NEEDS_RENDERER, tuple(shown[1][1]["buttons"]))


class EveryVersionFileIsRenamedTest(_OldLibrary):
    """The converter names each old version file `<id>_<n>.*` and drops `file` from the rows."""

    def lay_out(self):
        self.database("library.json", ["MAT2"])
        self.database("code.json", ["CODE2"])
        self.old_asset("MAT2")
        folder = os.path.join(self.old, "versions", "MAT2")
        for number in (1, 2):
            write(os.path.join(folder, "%d.mat" % number), "version %d\n" % number)
            write(os.path.join(folder, "%d.interface" % number), INTERFACE)
        write(os.path.join(folder, "Crimson-4.mat"), "version 4\n")
        write(os.path.join(folder, "Crimson-4.png"), b"picture 4")
        write(os.path.join(folder, "Cobalt-3.mat"), "a file no row names\n")
        write(os.path.join(folder, "versions.json"),
              {"active": 2, "versions": [{"n": 1, "name": "V1"},
                                         {"n": 2, "name": "V2", "file": "2"},
                                         {"n": 4, "name": "V4", "file": "Crimson-4"}]})
        code = self.at("code", "versions", "CODE2")
        write(os.path.join(code, "1.txt"), "print(1)\n")
        write(os.path.join(code, "Crimson-2.txt"), "print(2)\n")
        write(os.path.join(code, "versions.json"),
              {"active": 2, "versions": [{"n": 1, "name": "V1"},
                                         {"n": 2, "name": "V2", "file": "Crimson-2"}]})

    def ledger(self, *parts) -> dict:
        with open(os.path.join(*parts, "versions.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def test_every_old_file_takes_the_new_name(self):
        self.lay_out()
        self.assertEqual(library_conversion.DONE, self.convert()[0].status)
        folder = os.path.join(self.materials, "versions", "MAT2")
        self.assertEqual(["MAT2_1.json", "MAT2_1.mat", "MAT2_2.json", "MAT2_2.mat",
                          "MAT2_3.mat", "MAT2_4.mat", "MAT2_4.png", "versions.json"],
                         sorted(os.listdir(folder)))
        rows = self.ledger(folder)["versions"]
        self.assertEqual([[], [], []], [[key for key in row if key == "file"] for row in rows])
        self.assertTrue(versions.version_file(self.prefs, "MAT2", 1).endswith("MAT2_1.mat"))
        self.assertTrue(versions.version_file(self.prefs, "MAT2", 4).endswith("MAT2_4.mat"))
        code = self.at("code", "versions", "CODE2")
        self.assertEqual(["CODE2_1.txt", "CODE2_2.txt", "versions.json"],
                         sorted(os.listdir(code)))
        self.assertEqual([None, None], [row.get("file") for row in self.ledger(code)["versions"]])

    def test_the_new_names_are_the_only_version_names(self):
        for relative, kind in (("materials/versions/MAT2/MAT2_3.mat", library_files.VERSION),
                               ("nodes/versions/N1/N1_12.json", library_files.VERSION),
                               ("code/versions/C1/C1_2.txt", library_files.VERSION),
                               ("materials/versions/MAT2/3.mat", library_files.UNKNOWN),
                               ("materials/versions/MAT2/Crimson-3.mat", library_files.UNKNOWN),
                               ("materials/versions/MAT2/OTHER_3.mat", library_files.UNKNOWN)):
            with self.subTest(relative=relative):
                self.assertEqual(kind, library_files.classify(relative)[0])


class OnlyTheConverterNamesFormat3Test(unittest.TestCase):
    """Every module but the converter reads 2.0 only: no old file, copy, key or module named."""

    NAMES = (".interface", ".builder.json", ".stamp.json", "_icon.png", '"mat/"',
             "LEGACY_ASSET_FOLDER",
             "library.json", "cops.json", "gradients.json", "notes.json", "icons.json",
             "favourites.json", "locations.json", "location_paths.json", "users.json",
             "prefs.json", "policy.json", "pre-adopt", "PRE_ADOPT",
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
                    if line.startswith("FENCE = "):    # a 2.0 library's own file, kept for older Amaze
                        continue
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
        """Neither a section write nor the save of its row replaces bytes that did not read."""
        path = write(asset_record.path_for(self.prefs, "BAD1", MATERIALS), "{nope")
        write(os.path.join(self.materials, "BAD1.mat"), "nodes of BAD1\n")
        self.assertEqual({"metadata": {}, "builder": {}}, asset_record.read(path))
        with self.assertRaises(OSError):
            asset_record.write_section(path, asset_record.METADATA, {"name": "n"})
        held = library_db.document(self.prefs, MATERIALS)
        self.assertTrue(held.put("assets", "BAD1", dict(ROW, id="BAD1")))
        test_support.settle_stamps()
        self.assertTrue(held.get("assets", "BAD1"), "premise: the row was saved")
        self.assertEqual(b"{nope", read_bytes(path), "a record that did not read was written over")

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

    def test_switching_back_keeps_the_metadata_and_takes_the_builder(self):
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


class TheRebuildReadsTheNewFileTest(_Library):
    """A lost database is rebuilt from each `<id>.json`'s metadata, and only from that."""

    def test_the_metadata_section_rebuilds_the_row(self):
        self.metadata("REB1")
        self.old_asset("REB2")
        self.old_asset("REB3", self.materials)
        rebuilt = repair.rebuild_from_stamps(self.dir)
        names = {row["id"] for row in rebuilt["assets"].values()}
        self.assertIn("REB1", names, "the rebuild could not read `<id>.json`")
        self.assertNotIn("REB2", names, "the rebuild read a format 3 stamp in mat/")
        self.assertNotIn("REB3", names, "the rebuild read a format 3 stamp beside the files")


class AnyIdTheWriterTakesIsReadBackTest(_Library):
    """`-1` and ids with `.`, `_` or `-` get an `<id>.json`; the rebuild and the checks see it."""

    def test_the_sentinel_row_is_written_and_rebuilt(self):
        write(os.path.join(self.materials, "-1.mat"), "nodes of -1\n")
        held = library_db.document(self.prefs, MATERIALS)
        self.assertTrue(held.put("assets", "-1", dict(ROW, id="-1", name="Sentinel")))
        test_support.settle_stamps()
        written = os.path.join(self.materials, "-1.json")
        self.assertTrue(os.path.exists(written), "premise: the writer takes the id -1")
        rebuilt = repair.rebuild_from_stamps(self.dir)
        self.assertIn("-1", {str(row["id"]) for row in rebuilt["assets"].values()})
        findings = repair.survey(self.dir)
        self.assertNotIn("materials/-1.json",
                         [entry[0] for entry in findings["unknown"]],
                         "Check Library called the file unknown")

    def test_an_unlisted_one_is_an_orphan_with_metadata(self):
        self.metadata("odd_id.1")
        findings = repair.survey(self.dir)
        self.assertIn("odd_id.1.json", findings["unaccounted"]["materials/"])
        self.assertIn("odd_id.1", repair.stamped_unlisted(findings))


class APairIsOneFolderTest(_Library):
    """A `.mat` in one folder and a `.json` in another are two halves, not a pair."""

    def test_halves_in_two_folders_are_no_pair(self):
        write(os.path.join(self.materials, "SPLIT1.mat"), "n\n")
        write(os.path.join(self.nodes, "SPLIT1.json"), {"builder": {"type": "x"}})
        write(os.path.join(self.old, "SPLIT2.mat"), "n\n")
        write(os.path.join(self.materials, "SPLIT2.json"), {"builder": {"type": "x"}})
        write(os.path.join(self.materials, "WHOLE1.mat"), "n\n")
        write(os.path.join(self.materials, "WHOLE1.json"), {"builder": {"type": "x"}})
        self.assertEqual(["WHOLE1"], repair.complete_pairs(repair.survey(self.dir)))


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
        self.assertEqual(render, model.capture_path(row), "a capture lands somewhere else")
        before = self.trashed()
        write(model.capture_path(row), "captured")
        for face in ("generic", "image", "generic", "image"):    # both directions, twice
            self.assertTrue(model.set_tile_icon(row, {"face": face}))
        with open(render, encoding="utf-8") as handle:
            self.assertEqual("captured", handle.read())
        self.assertEqual(before, self.trashed(), "a face switch moved a picture to the trash")

    def test_a_format_3_picture_is_never_the_tile_s(self):
        from amaze.core import tile_icons
        os.remove(os.path.join(self.materials, self.ASSET + ".png"))
        for folder in ("img", "captures"):
            write(self.at(folder, self.ASSET + ".png"), b"old")
        self.assertEqual(os.path.join(self.materials, self.ASSET + ".png"),
                         tile_icons.thumbnail_path(self.prefs, self.ASSET, MATERIALS))

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
        self.assertIsNotNone(tile_icons.chosen_image(model, row), "no icon was composed")

    def test_check_library_on_the_new_layout(self):
        os.remove(os.path.join(self.materials, self.ASSET + ".png"))
        write(os.path.join(self.materials, "ORPHANPIC1.png"), "an unlisted picture")
        findings = repair.survey(self.dir)
        self.assertIn(self.ASSET,
                      [one for one, _name in findings["missing_renders"][MATERIALS]])
        self.assertIn("ORPHANPIC1.png", findings["unaccounted"]["materials/"])


class PicturesLiveInTheirSectionTest(_Library):
    """File captures are `files/<key hash>.png`; a comment's picture is in its section's `comments`."""

    def test_the_two_old_folders_are_emptied_into_the_sections(self):
        capture, shown, stray = "ab" * 20, "c" * 32 + ".png", "d" * 32 + ".png"
        write(self.at("captures", "file_%s.png" % capture), b"a file's capture")
        write(self.at("img", "comments", shown), b"a picture in a comment")
        write(self.at("img", "comments", stray), b"a picture no comment shows")
        write(self.at("img", "0123.png.lock"), b"")
        held = guard.Guard(self.dir)
        reading = held.read(MATERIALS)
        asset_id = sorted(reading.document["assets"])[0]
        document = json.loads(json.dumps(reading.document))
        document.setdefault("comments", {})[asset_id] = {"items": [
            {"t": "image", "src": "img/comments/" + shown, "text": ""}]}
        change = held.change(test_support.FIXTURE_USER)
        change.put(reading.ticket, document)
        change.commit()
        self.assertTrue(library_conversion.needs_rehoming(self.dir))
        self.assertEqual(2, library_conversion.rehome_pictures(self.dir, test_support.FIXTURE_USER))
        self.assertEqual(b"a file's capture", read_bytes(self.at("files", capture + ".png")))
        self.assertEqual(b"a picture in a comment",
                         read_bytes(self.at("materials", "comments", shown)))
        item = guard.Guard(self.dir).read(MATERIALS).document["comments"][asset_id]["items"][0]
        self.assertEqual("materials/comments/" + shown, item["src"])
        self.assertEqual(1, trashed(self.dir), "the picture no comment shows did not go to the trash")
        self.assertFalse(os.path.exists(self.at("img")) or os.path.exists(self.at("captures")))
        self.assertFalse(library_conversion.needs_rehoming(self.dir))
        for relative in ("files/%s.png" % capture, "materials/comments/" + shown):
            self.assertNotEqual(library_files.UNKNOWN, library_files.classify(relative)[0], relative)

    def test_a_new_comment_picture_lands_in_its_section(self):
        from amaze.core import captures, notes
        source = write(os.path.join(test_support.scratch_dir("amaze_pic_"), "p.png"), b"png")
        self.addCleanup(shutil.rmtree, os.path.dirname(source), True)
        for section, folder in (("material", "materials"), ("gradient", "colors"),
                                ("file", "files")):
            src = notes.adopt_image(self.prefs, source, notes.note_key(section, "X1"))
            self.assertTrue(src.startswith(folder + "/comments/"), (section, src))
            self.assertTrue(os.path.isfile(self.at(*src.split("/"))))
        self.assertEqual("files", os.path.basename(os.path.dirname(
            captures.file_path(self.prefs, "loc:L1/a.exr"))))


class AFreshLibraryTest(unittest.TestCase):
    """A new library is born with a folder per asset section and no `mat/`."""

    def test_the_section_folders_are_made(self):
        from amaze.actions import library as library_actions
        folder = test_support.scratch_dir("amaze_fresh_sections_")
        self.addCleanup(shutil.rmtree, folder, True)
        library_actions.ensure_library_dirs(types.SimpleNamespace(dir=folder, img_dir="img/"))
        self.assertEqual(sorted(["img", "materials", "nodes"]), sorted(os.listdir(folder)))
        self.assertFalse(library_conversion.needs_conversion(folder))


class OldFilesBesideANewOneAreLeftoversTest(_Library):
    """Format 3 files beside `<id>.json` are leftovers the conversion did not take."""

    def test_beside_a_converted_asset_they_are_leftovers(self):
        asset_id = "139888336268658010"
        self.old_asset(asset_id, self.materials, stamp=False)
        findings = repair.survey(self.dir)
        kinds = {relative: kind for relative, kind, _size, _when in findings["leftovers"]}
        self.assertEqual(library_files.SUPERSEDED,
                         kinds.get("materials/%s.interface" % asset_id), kinds)
        self.assertFalse(any(name.endswith(".interface") for names in
                             findings["unaccounted"].values() for name in names))


class EveryOldStoreArrivesTest(unittest.TestCase):
    """Each old root file lands in the right section of the right 2.0 database."""

    USER = "a" * 32    # the user converting
    PEER = "b" * 32

    def setUp(self):
        self.dir = test_support.scratch_dir("amaze_old_stores_")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def lay(self, name: str, data) -> None:
        write(os.path.join(self.dir, name), data)

    def section(self, rows: list, name="library.json", **document) -> None:
        self.lay(name, dict({"format": 3, "categories": [], "assets": rows}, **document))

    def built(self, **kwargs) -> dict:
        return library_conversion.build_databases(self.dir, user=self.USER, **kwargs)

    def test_comments_of_assets_and_of_files(self):
        self.section([{"id": "A1", "name": "One"}])
        item = {"t": "text", "text": "on the asset", "id": "c1", "author": self.PEER}
        self.lay("notes.json", {"notes": {
            "material:A1": {"items": [item]},
            "file:/x/a.exr": {"items": [{"t": "todo", "label": "on the file", "done": True,
                                         "id": "c2", "author": self.PEER}]}}})
        built = self.built()
        self.assertEqual([item], built[MATERIALS]["comments"]["A1"]["items"])
        self.assertEqual("on the file",
                         built[library_files.FILES]["comments"]["/x/a.exr"]["items"][0]["label"])

    def test_the_first_comment_shape_reads_as_items(self):
        self.section([{"id": "A1"}])
        self.lay("notes.json", {"notes": {"material:A1": {
            "text": "old words", "todos": [{"label": "old item", "done": True}]}}})
        items = self.built()[MATERIALS]["comments"]["A1"]["items"]
        self.assertEqual([("text", "old words"), ("todo", "old item")],
                         [(one["t"], one.get("text", one.get("label"))) for one in items])
        self.assertTrue(items[1]["done"])

    def test_a_comment_item_with_no_author_and_no_id_is_kept_with_an_id(self):
        self.section([{"id": "A1"}])
        self.lay("notes.json", {"notes": {"material:A1": {"items": [
            {"t": "text", "text": "anonymous"}, {"t": "text", "text": "also"}]}}})
        items = self.built()[MATERIALS]["comments"]["A1"]["items"]
        self.assertEqual(["anonymous", "also"], [one["text"] for one in items])
        self.assertEqual(["", ""], [one["author"] for one in items])
        self.assertEqual(2, len({one["id"] for one in items if one["id"]}))

    def test_icons_of_assets_and_of_files(self):
        self.section([{"id": "A1"}, {"id": "A2"}])
        spec = {"name": "circle", "bg": "#e0523a", "ink": "dark"}
        self.lay("icons.json", {"icons": {"A1": spec, "/x/a.exr": dict(spec, name="map"),
                                          "A2": {"face": "capture"}, "GONE": spec}})
        built = self.built()
        self.assertEqual({"A1": spec}, built[MATERIALS]["icons"])
        self.assertEqual({"/x/a.exr": dict(spec, name="map")},
                         built[library_files.FILES]["icons"])

    def test_stars_per_user_of_assets_and_of_files(self):
        self.section([{"id": "A1"}, {"id": "A2"}])
        self.lay("favourites.json", {"favourites": {
            self.PEER + "|A1": True, self.PEER + "|/x/a.exr": True, "A2": True}})
        built = self.built()
        self.assertEqual({self.PEER: {"A1": True}, self.USER: {"A2": True}},
                         built[MATERIALS]["stars"], "a star from before users is not the converter")
        self.assertEqual({self.PEER: {"/x/a.exr": True}}, built[library_files.FILES]["stars"])

    def test_the_stars_this_computer_kept_in_its_settings_arrive(self):
        """The machine stars of the settings file become the converting user, and only theirs."""
        self.section([{"id": "A1"}, {"id": "A2"}])
        held = types.SimpleNamespace(data={"material_favorites": ["A1", " "]})
        stars = library_conversion.machine_stars(held)
        self.assertEqual(["A1"], stars)
        built = self.built(machine_stars=stars)
        self.assertEqual({self.USER: {"A1": True}}, built[MATERIALS]["stars"])
        self.assertEqual([], library_conversion.machine_stars(types.SimpleNamespace(data={})))

    def test_locations_and_their_paths(self):
        self.lay("location_paths.json", {"location_paths": {
            "L1": {"path": "/proj/tex"}, "L2": {"path": "/proj/tex/"}, "L3": {"path": "/lib"}}})
        self.lay("locations.json", {"locations": {
            self.PEER + "|/proj/tex": {"registered": True, "label": "Textures"},
            "loc:L3": {"registered": True}}})
        self.lay("notes.json", {"notes": {"file:/proj/tex/a.exr": {"items": [
            {"t": "text", "text": "under it"}]}, "file:loc:L2/b.exr": {"items": [
                {"t": "text", "text": "rival id"}]}}})
        files = self.built()[library_files.FILES]
        self.assertEqual({"L1": {"path": "/proj/tex"}, "L3": {"path": "/lib"}}, files["paths"],
                         "two ids at one path were not collapsed to one")
        every = ["geometry", "hip", "image", "other"]
        self.assertEqual({self.PEER: {"loc:L1": {"registered": True, "label": "Textures",
                                                 "kinds": every}},
                          self.USER: {"loc:L3": {"registered": True, "kinds": every}}},
                         files["locations"])
        self.assertEqual(["loc:L1/a.exr", "loc:L1/b.exr"], sorted(files["comments"]))

    def test_a_location_from_before_show_is_given_the_ticks_it_listed_by(self):
        known = ["geometry", "hip", "image"]
        for show_all, show_unknown, kinds in ((None, True, known + ["other"]),
                                              (None, False, known),
                                              (True, False, known + ["other"]),
                                              (False, True, known),
                                              ("ticked", True, ["image"])):
            with self.subTest(show_all=show_all, show_unknown=show_unknown):
                record = {"registered": True}
                if show_all == "ticked":
                    record["kinds"] = ["image"]
                elif show_all is not None:
                    record["show_all"] = show_all
                self.lay("locations.json", {"locations": {"loc:L3": record}})
                built = self.built(show_unknown=show_unknown)[library_files.FILES]
                self.assertEqual(kinds, built["locations"][self.USER]["loc:L3"]["kinds"])

    def test_users(self):
        self.lay("users.json", {"users": {self.PEER: {"name": "  First User "},
                                          "c" * 32: {"name": "  "}}})
        self.assertEqual({self.PEER: {"name": "First User"}},
                         self.built()[library_files.MASTER]["users"])

    def test_shared_settings(self):
        self.lay("prefs.json", {"prefs": {"rendersize": {"value": 512}, "odd": {"x": 1}}})
        self.assertEqual({"rendersize": {"value": 512}},
                         self.built()[library_files.MASTER]["settings"])

    def test_the_policy(self):
        self.lay(library_conversion.OLD_POLICY, {"library_version": 3, "allow_overwrite": True})
        policy = self.built()[library_files.MASTER]["policy"]
        self.assertEqual({"value": True}, policy["allow_overwrite"])
        self.assertEqual({"version": library_policy.LIBRARY_VERSION}, policy["library"])

    def test_the_four_marker_files_in_both_spellings(self):
        for marker in library_conversion.OLD_MARKS:
            with self.subTest(marker=marker):
                for one in library_conversion.OLD_MARKS:
                    if os.path.exists(os.path.join(self.dir, one)):
                        os.remove(os.path.join(self.dir, one))
                self.lay(marker, "seeded\n")
                marks = self.built()[library_files.MASTER]["marks"]
                self.assertEqual({library_conversion.OLD_MARKS[marker]: {"offered": True}}, marks)

    def test_category_order_and_colours(self):
        self.section([{"id": "A1", "categories": ["Roof"]}],
                     categories=["_All", "Walls", "Floors"], category_colors={"Floors": "#123456"})
        self.assertEqual({"Walls": {"order": 0}, "Floors": {"order": 1, "color": "#123456"},
                          "Roof": {"order": 2}}, self.built()[MATERIALS]["categories"])

    def test_a_comma_string_category_is_split(self):
        self.section([{"id": "A1", "categories": "Walls, Floors ,,"}])
        built = self.built()[MATERIALS]
        self.assertEqual(["Walls", "Floors"], built["assets"]["A1"]["categories"])
        self.assertEqual(["Walls", "Floors"], list(built["categories"]))

    def test_about_and_description_become_the_comment_first_and_once(self):
        """The retired text lands above what the user wrote, once, and the row keeps no copy."""
        self.section([{"id": "A1", "about": "Credit 1", "description": "Described 1"},
                      {"id": "A2", "about": "Credit 2"}])
        mine = {"t": "todo", "label": "check the roughness", "done": False, "id": "m1",
                "author": self.PEER}
        self.lay("notes.json", {"notes": {"material:A1": {"items": [mine]},
                                          "material:A2": {"items": [
                                              {"t": "text", "text": "Credit 2"}]}}})
        built = self.built()[MATERIALS]
        self.assertEqual(["Credit 1", "Described 1", "check the roughness"],
                         [one.get("text", one.get("label"))
                          for one in built["comments"]["A1"]["items"]])
        self.assertEqual(["Credit 2"], [one["text"] for one in built["comments"]["A2"]["items"]],
                         "the credit was written into the comment a second time")
        for row in built["assets"].values():
            self.assertFalse({"about", "description"} & set(row), "the row kept a retired field")

    def test_the_retired_row_fields_are_dropped(self):
        self.section([{"id": "A1", "favorite": True, "icon": {"name": "box"}, "builder": {}}])
        built = self.built()[MATERIALS]
        self.assertEqual({"id": "A1"}, built["assets"]["A1"])
        self.assertEqual({}, built["stars"], "a row field star became a star")

    def test_older_spellings_of_the_id_and_a_row_with_none(self):
        self.section([{"mat_id": "M1"}, {"uid": "U1"}, {"name": "bare"}, {"id": "K1"}],
                     name="gradients.json")
        first = self.built()[library_files.COLORS]["assets"]
        again = self.built()[library_files.COLORS]["assets"]
        self.assertIn("M1", first)
        self.assertIn("U1", first)
        self.assertIn("K1", first, "an id already there was replaced")
        minted = [key for key, row in first.items() if row.get("name") == "bare"]
        self.assertEqual(1, len(minted), "a row with no id was given none")
        self.assertEqual(minted, [key for key, row in again.items() if row.get("name") == "bare"],
                         "the minted id changes between two runs, orphaning its comments")
        self.assertEqual({"id"}, set(first["M1"]), "the old spelling of the id stayed on the row")


if __name__ == "__main__":
    unittest.main()
