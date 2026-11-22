"""Check Library 2.0: the report shows what `guard` reads, and every fix writes through `guard`."""

import datetime
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze import messages  # noqa: E402
from amaze.core import asset_record, guard, library_check, library_files, repair  # noqa: E402
from amaze.tests import test_support  # noqa: E402

MATERIALS = library_files.MATERIALS
NODES = library_files.NODES
BUILDER = {"type": "subnet", "interface": "", "values": {}}


def _write(directory: str, name: str, document: dict) -> None:
    with open(os.path.join(directory, name), "wb") as handle:
        handle.write(guard.encode(document))


def _read(directory: str, name: str) -> dict:
    with open(os.path.join(directory, name), encoding="utf-8") as handle:
        return json.load(handle)


class _Library(unittest.TestCase):
    """A small 2.0 library: two materials with their files and metadata, open in no session."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_check_") + os.sep
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.materials = os.path.join(self.dir, "materials")
        os.makedirs(self.materials)
        _write(self.dir, library_files.MASTER, {"manifest": {MATERIALS: {"by": ""}},
                                                "users": {}})
        rows = {}
        for asset_id, name in (("AAA1", "Brick"), ("AAA2", "Oak")):
            row = {"id": asset_id, "name": name, "categories": ["Walls"], "renderer": "Karma"}
            rows[asset_id] = row
            self.asset(asset_id, row)
        _write(self.dir, MATERIALS, {"assets": rows, "categories": {"Walls": {"order": 0}}})

    def asset(self, asset_id: str, metadata=None, folder=None) -> None:
        """An asset's `.mat`, `.png` and `<id>.json` in `folder`, the metadata when given."""
        folder = folder or self.materials
        os.makedirs(folder, exist_ok=True)
        for suffix in (".mat", ".png"):
            with open(os.path.join(folder, asset_id + suffix), "wb") as handle:
                handle.write(b"x")
        document = {"format": asset_record.FORMAT, asset_record.BUILDER: BUILDER}
        if metadata is not None:
            document[asset_record.METADATA] = dict(metadata)
        with open(os.path.join(folder, asset_id + ".json"), "wb") as handle:
            handle.write(asset_record.encode(document))

    def survey(self):
        return repair.survey(self.dir, "img/")

    def trash_holds(self, relative: str) -> bool:
        day = datetime.date.today().isoformat()
        return os.path.exists(os.path.join(self.dir, "trash", day, *relative.split("/")))


class TheReportUsesTheGuardsVerdictsTest(_Library):

    def test_a_corrupt_database_is_named_and_move_aside_raises(self):
        with open(os.path.join(self.dir, MATERIALS), "w", encoding="utf-8") as handle:
            handle.write("{ ruined")
        self.asset("ORPHAN1")
        findings = self.survey()
        states = {entry["filename"]: entry["state"] for entry in findings["lists"]}
        self.assertEqual("unreadable", states[MATERIALS])
        self.assertFalse(findings["complete"])
        self.assertIn("Materials: the database is corrupt/unreadable.",
                      "\n".join(repair.report_lines(findings)))
        with self.assertRaises(ValueError):
            repair.move_aside(findings, "unlisted", guard_session=False)
        self.assertTrue(os.path.exists(os.path.join(self.materials, "ORPHAN1.mat")))

    def test_a_newer_database_is_named_and_read_only(self):
        _write(self.dir, NODES, {"assets": {}, "format": 99})
        findings = self.survey()
        self.assertIn("Nodes: the database was saved by a newer Amaze",
                      "\n".join(repair.report_lines(findings)))

    def test_every_database_reads_fine_with_its_count(self):
        text = "\n".join(repair.report_lines(self.survey()))
        self.assertIn("Every database reads fine: 0 users and 2 materials.", text)
        self.assertIn("Nothing is saved yet in Nodes, Code, Colors and Files.", text)
        self.assertIn("The library's trash is empty", text)


class TheFixesActThroughTheGuardTest(_Library):

    def test_restore_a_backup_keeps_the_database_you_have_as_an_undo_copy(self):
        reading = guard.Guard(self.dir).read(MATERIALS)
        change = guard.Guard(self.dir).change("u")
        change.put(reading.ticket, {"assets": {}})
        change.commit()
        findings = self.survey()
        offers = repair.offered_copies(findings)
        self.assertTrue(offers, "the backup of the two materials is not offered")
        filename, backup, _snap, _now = offers[0]
        done = repair.restore_backup(findings, filename, backup, guard_session=False)
        self.assertEqual({"AAA1", "AAA2"}, set(_read(self.dir, MATERIALS)["assets"]))
        self.assertTrue(done["undo"].endswith(guard.UNDO_TAIL), "nothing kept to undo")

    def test_orphaned_files_go_to_the_librarys_trash(self):
        with open(os.path.join(self.materials, "STRAY1.png"), "wb") as handle:
            handle.write(b"x")
        findings = self.survey()
        self.assertEqual(["STRAY1.png"], findings["unaccounted"]["materials/"])
        result = repair.move_aside(findings, "unlisted", guard_session=False)
        self.assertEqual(["STRAY1.png"], result["moved"])
        self.assertFalse(os.path.exists(os.path.join(self.materials, "STRAY1.png")))
        self.assertTrue(self.trash_holds("materials/STRAY1.png"))

    def test_orphaned_materials_are_recovered_from_their_metadata(self):
        self.asset("NEW1", {"id": "NEW1", "name": "Slate", "categories": ["Roofs"],
                            "renderer": "Karma"})
        findings = self.survey()
        self.assertEqual({MATERIALS: ["NEW1"]}, repair.recoverable(findings))
        result = repair.recover(findings, guard_session=False)
        self.assertEqual(["NEW1"], result[MATERIALS]["added"])
        stored = _read(self.dir, MATERIALS)
        self.assertEqual("Slate", stored["assets"]["NEW1"]["name"])
        self.assertIn("Roofs", stored["categories"])

    def test_each_folder_s_pairs_are_recovered_into_its_own_section(self):
        """Without asking: pairs in the materials folder go to Materials, in nodes to Nodes."""
        nodes = os.path.join(self.dir, "nodes")
        long_id = "ABCDEF0123456789ABCDEF0123456789"
        self.asset(long_id, folder=nodes)
        self.asset("RIG1", {"id": "RIG1", "name": "Rig", "renderer": "Karma"}, nodes)
        os.rename(os.path.join(nodes, "RIG1.png"), os.path.join(self.materials, "RIG1.png"))
        self.asset("MAT9")
        findings = self.survey()
        self.assertEqual({MATERIALS: ["MAT9"], NODES: [long_id, "RIG1"]},
                         repair.recoverable(findings))
        result = repair.recover(findings, guard_session=False)
        self.assertEqual([long_id, "RIG1"], sorted(result[NODES]["added"]))
        self.assertEqual(["MAT9"], result[MATERIALS]["added"])
        node_rows = _read(self.dir, NODES)["assets"]
        self.assertEqual("Recovered " + long_id, node_rows[long_id]["name"],
                         "an asset whose metadata cannot be read is not named by its whole id")
        self.assertEqual("Rig", node_rows["RIG1"]["name"])
        self.assertEqual("Recovered MAT9", _read(self.dir, MATERIALS)["assets"]["MAT9"]["name"])
        self.assertTrue(os.path.exists(os.path.join(nodes, "RIG1.png")),
                        "a file in the other folder was not moved to the row's folder")
        self.assertFalse(os.path.exists(os.path.join(self.materials, "RIG1.png")))

    def test_a_lost_database_is_rebuilt_from_each_assets_metadata(self):
        for asset_id, name in (("AAA1", "Brick"), ("AAA2", "Oak")):
            self.asset(asset_id, {"id": asset_id, "name": name, "categories": ["Walls"],
                                  "renderer": "Karma"})
        with open(os.path.join(self.dir, MATERIALS), "w", encoding="utf-8") as handle:
            handle.write("{ ruined")
        done = repair.rebuild(self.dir, MATERIALS, guard_session=False)
        self.assertEqual({"assets": 2, "damaged": 0}, done)
        self.assertEqual({"AAA1", "AAA2"}, set(_read(self.dir, MATERIALS)["assets"]))

    def test_a_corrupt_database_offers_its_backups_and_the_rebuild_and_picks_neither(self):
        from amaze.dialogs import repair_dialog
        test_support.backup_now(self.dir, MATERIALS)
        with open(os.path.join(self.dir, MATERIALS), "w", encoding="utf-8") as handle:
            handle.write("{ ruined")
        findings = self.survey()
        _labels, keys = repair_dialog._every_choice(findings, True)
        self.assertIn("restore", keys)
        self.assertIn("rebuild", keys)
        self.assertFalse(hasattr(repair, "repair_index"), "a function still picks the fix")
        with open(os.path.join(self.dir, MATERIALS), encoding="utf-8") as handle:
            self.assertEqual("{ ruined", handle.read())

    def test_rows_with_no_category_are_put_in_uncategorized(self):
        stored = _read(self.dir, MATERIALS)
        stored["assets"]["AAA2"]["categories"] = []
        _write(self.dir, MATERIALS, stored)
        findings = self.survey()
        done = repair.rescue_uncategorised(findings, guard_session=False)
        self.assertEqual({MATERIALS: 1}, done)
        self.assertEqual([repair.UNCATEGORISED],
                         _read(self.dir, MATERIALS)["assets"]["AAA2"]["categories"])


class TheFolderDecidesTheSectionTest(_Library):
    """An orphaned asset belongs to the section whose folder holds it, whatever its renderer."""

    def setUp(self):
        super().setUp()
        self.nodes = os.path.join(self.dir, "nodes")

    def test_a_pair_in_the_nodes_folder_is_not_recovered_into_materials(self):
        self.asset("NODE2", {"id": "NODE2", "name": "Rig", "renderer": "Karma"}, self.nodes)
        findings = self.survey()
        self.assertEqual({NODES: ["NODE2"]}, repair.recoverable(findings))
        self.assertEqual(["NODE2"], [one for one, _record in repair.on_record(findings, NODES)])

    def test_a_pair_in_the_materials_folder_is_a_material_whatever_its_renderer(self):
        self.asset("NEW2", {"id": "NEW2", "name": "Glass", "renderer": ""})
        self.asset("NEW3", {"id": "NEW3", "name": "Moss", "renderer": "sop"})
        findings = self.survey()
        self.assertEqual({MATERIALS: ["NEW2", "NEW3"]}, repair.recoverable(findings))

    def test_one_recover_button_and_no_question_about_the_section(self):
        from amaze import messages
        from amaze.dialogs import repair_dialog
        self.asset("NEW2", {"id": "NEW2", "name": "Glass", "renderer": ""})
        self.asset("NODE2", None, self.nodes)
        findings = self.survey()
        labels, keys = repair_dialog._every_choice(findings, True)
        self.assertEqual(["recover"], [key for key in keys if key in (
            "recover", "add-back", "reattach")])
        self.assertIn(messages.BUTTON_REPAIR_RECOVER % "1 Material and 1 Node", labels)
        asked = []

        def display(text, **kwargs):
            asked.append(text)
            return 0
        fake_ui = mock.Mock(displayMessage=display,
                            selectFromList=mock.Mock(side_effect=AssertionError("asked")))
        with mock.patch.object(repair_dialog.hou, "ui", fake_ui, create=True):
            self.assertTrue(repair_dialog.act(findings, "recover", guard=False))
        self.assertEqual(messages.CONFIRM_RECOVER % "1 material and 1 node", asked[0])
        self.assertIn("NEW2", _read(self.dir, MATERIALS)["assets"])
        self.assertIn("NODE2", _read(self.dir, NODES)["assets"])

    def test_a_rebuild_takes_only_the_metadata_in_its_own_folder(self):
        self.asset("NODE3", {"id": "NODE3", "name": "Rig", "renderer": "Karma"}, self.nodes)
        self.asset("NEW4", {"id": "NEW4", "name": "Moss", "renderer": "sop"})
        built = repair.rebuild_from_metadata(self.dir, MATERIALS)
        self.assertEqual({"AAA1", "AAA2", "NEW4"}, set(built["assets"]))
        self.assertEqual({"NODE3"}, set(repair.rebuild_from_metadata(self.dir, NODES)["assets"]))


def _make(path: str, data: bytes = b"x", age_s: float = 0) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    if age_s:
        when = time.time() - age_s
        os.utime(path, (when, when))
    return path


class EverySentenceOfTheReportTest(_Library):
    """One test per sentence the report can show, each set up so that sentence applies."""

    def text(self, findings=None) -> str:
        return "\n".join(repair.report_lines(findings or self.survey()))

    def corrupt(self, name=MATERIALS):
        with open(os.path.join(self.dir, name), "w", encoding="utf-8") as handle:
            handle.write("{ ruined")

    def test_it_opens_by_naming_the_library_and_its_databases(self):
        self.assertIn("Amaze looked at the library in %s. It keeps a database for each of its "
                      "sections - Materials, Nodes, Code, Colors and Files - and one for the "
                      "library itself." % os.path.normpath(self.dir), self.text())

    def test_all_is_well(self):
        text = self.text()
        for line in ("There are no orphaned files in `materials/`",
                     "Every material and node in the databases has its files, and every one "
                     "that can have a render has one.",
                     "There are no temporary files from a save that did not finish, and every "
                     "file in the library folder has a name Amaze knows.",
                     "Every material and node has a category."):
            with self.subTest(line=line):
                self.assertIn(line, text)

    def test_an_empty_database_holds_its_orphaned_files(self):
        _write(self.dir, MATERIALS, {"assets": {}})
        text = self.text()
        self.assertIn("Materials: the database is there and holds nothing.", text)
        self.assertIn("A database that holds nothing looks the same whether nothing was ever "
                      "saved there or it failed to load this time", text)
        self.assertIn("None of them will be moved to the trash while a database that may own "
                      "them holds nothing", text)

    def test_orphaned_files(self):
        _make(os.path.join(self.materials, "STRAY1.png"))
        self.assertIn("1 file in the materials folder (STRAY1.png) is orphaned: no database "
                      "names it. Either they belong to something whose database was lost, or "
                      "nothing needs them any more.", self.text())

    def test_a_missing_database(self):
        os.remove(os.path.join(self.dir, MATERIALS))
        text = self.text()
        self.assertIn("Materials: there is no database for it in the library folder, though "
                      "Amaze can see there was one here before.", text)
        self.assertIn("Amaze could not check the Materials database either, so some of those "
                      "files may be its.", text)

    def test_the_other_databases_read_fine(self):
        self.corrupt()
        self.assertIn("The other databases read fine: 0 users.", self.text())

    def test_a_folder_that_cannot_be_listed(self):
        test_support.refuse_listing(self, self.materials)
        self.assertIn("Amaze could not look inside the materials folder, so it cannot say "
                      "whether there are orphaned files in there.", self.text())

    def test_a_row_whose_files_are_missing(self):
        os.remove(os.path.join(self.materials, "AAA1.mat"))
        self.assertIn("1 material is in the Materials database, but its files are missing: "
                      "Brick. A file that has not finished syncing looks the same as one that "
                      "is gone.", self.text())

    def test_a_row_with_no_render(self):
        os.remove(os.path.join(self.materials, "AAA1.png"))
        text = self.text()
        self.assertIn("No thumbnail image yet for 1 material - select it in Amaze and use "
                      "Render Image when convenient", text)
        self.assertIn("Every material and node in the databases has its files.", text)

    def test_leftovers_amaze_made(self):
        _make(os.path.join(self.materials, "AAA1.rendering.png"), age_s=2 * 3600)
        _make(os.path.join(self.materials, "AAA1.interface"))
        _make(os.path.join(self.materials, "AAA2 2.png"))
        text = self.text()
        self.assertIn("Amaze made 3 files here that nothing needs any more: 1 temporary file "
                      "from a save that did not finish, 1 file of the older format whose "
                      "content is now in the asset's .json and 1 conflict copy a sync service "
                      "made of a file still here.", text)

    def test_conflict_copies_left_where_they_are(self):
        _make(os.path.join(self.materials, "GONE1 2.png"))
        _make(os.path.join(self.materials, "AAA1 2.png"), b"y")
        text = self.text()
        self.assertIn("`materials/GONE1 2.png` looks like a conflict copy of "
                      "`materials/GONE1.png`, which is not here, so it is left where it is.", text)
        self.assertIn("`materials/AAA1 2.png` is a conflict copy of `materials/AAA1.png`, from ",
                      text)
        self.assertIn("and the two differ, so it is left where it is.", text)

    def test_files_amaze_does_not_know(self):
        _make(os.path.join(self.dir, "notes.txt"))
        self.assertIn("This is not a file Amaze knows, so it is left where it is:\n  `notes.txt`",
                      self.text())
        _make(os.path.join(self.dir, "stuff", "a.bin"))
        text = self.text()
        self.assertIn("These 2 are not files Amaze knows, so they are left where they are:", text)
        self.assertIn("`stuff/` - a folder of 1 file", text)

    def test_rows_with_no_category(self):
        stored = _read(self.dir, MATERIALS)
        stored["assets"]["AAA2"]["categories"] = []
        _write(self.dir, MATERIALS, stored)
        self.assertIn("1 material has no category, so it can be put in Uncategorized.",
                      self.text())

    def test_a_shrunk_database(self):
        rows = {"S%d" % n: {"id": "S%d" % n, "name": "S", "categories": ["Walls"]}
                for n in range(6)}
        _write(self.dir, MATERIALS, {"assets": rows})
        test_support.backup_now(self.dir, MATERIALS)
        _write(self.dir, MATERIALS, {"assets": dict(list(rows.items())[:2])})
        self.assertIn("Your Materials database holds 2 materials, but its newest backup holds "
                      "6 materials. If you did not remove them yourself, that backup can be "
                      "restored.", self.text())

    def test_the_backups_of_a_database_in_trouble(self):
        self.corrupt()
        self.assertIn("Materials: there are no backups of this database, so there is nothing "
                      "to restore. Your materials' own files and thumbnails are still in the "
                      "library folder either way.", self.text())
        _write(self.dir, MATERIALS, _read_raw_rows(self))
        test_support.backup_now(self.dir, MATERIALS)
        self.corrupt()
        self.assertRegex(self.text(), r"Materials: backups - from [0-9: -]+, 2 saved materials\.")

    def test_the_trash_line_once_it_holds_files(self):
        _make(os.path.join(self.materials, "STRAY1.png"))
        repair.move_aside(self.survey(), "unlisted", guard_session=False)
        self.assertIn("The library's trash holds 1 file (1 KB), moved there on 1 day. Each "
                      "day's files are deleted after 30 days, and the oldest go on ", self.text())

    def test_what_can_be_recovered(self):
        self.asset("NEW1", {"id": "NEW1", "name": "Slate", "renderer": "Karma"})
        self.asset("NODE1")
        self.asset("RIG1", {"id": "RIG1", "name": "Rig", "renderer": "Karma"},
                   os.path.join(self.dir, "nodes"))
        _make(os.path.join(self.materials, "LONE1.png"))
        text = self.text()
        self.assertIn("Recover puts 2 materials (Slate and NODE1) in the Materials database "
                      "and 1 node (Rig) in the Nodes database. Each goes to the section whose "
                      "folder holds its files.", text)
        self.assertIn("The rest are halves of an asset whose other file is not in the folder, "
                      "so they can only be moved to the trash.", text)
        self.assertIn("Moving files to the trash leaves 6 files where they are: the metadata "
                      "of what they belong to is saved beside them, so they can still be "
                      "recovered.", text)
        for old in ("add back", "added back", "put back", "to a section"):
            self.assertNotIn(old, text.lower(), "the report still says " + old)


def _read_raw_rows(case) -> dict:
    """The setUp's two rows, as the Materials database held them."""
    rows = {}
    for asset_id, name in (("AAA1", "Brick"), ("AAA2", "Oak")):
        rows[asset_id] = {"id": asset_id, "name": name, "categories": ["Walls"],
                          "renderer": "Karma"}
    return {"assets": rows, "categories": {"Walls": {"order": 0}}}


class TheFilesSectionTest(unittest.TestCase):
    """The Files section's sentences and fixes, on a fixture library with this user's locations."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.prefs = test_support.fixture_prefs(self)
        self.folder = test_support.scratch_dir("amaze_check_files_")
        self.addCleanup(shutil.rmtree, self.folder, True)

    def text(self, findings) -> str:
        return "\n".join(repair.report_lines(findings))

    def test_every_folder_is_here_and_every_star_too(self):
        self.assertIn("Every folder in the Files section is on this computer, and every starred "
                      "file is still there.", self.text(repair.survey(self.prefs)))

    def test_a_folder_on_a_drive_that_is_not_connected(self):
        self.prefs.add_file_folder(self.folder)
        gone = os.path.join(self.folder, "away")
        self.prefs.add_file_folder(gone)
        with mock.patch.object(repair.hostos, "volume_unreachable",
                               lambda path: os.path.normpath(path) == os.path.normpath(gone)):
            findings = repair.survey(self.prefs)
        self.assertIn("1 folder is on a drive that is not connected, so it is left as it is - it "
                      "will be back when the drive is.", self.text(findings))


class TheOtherFixesTest(_Library):
    """Fixes the tests above leave out: leftovers, unknown files, stars, locations, trash."""

    def files_prefs(self):
        test_support.reset_database_singletons()
        prefs = test_support.fixture_prefs(self)
        folder = test_support.scratch_dir("amaze_check_fix_")
        self.addCleanup(shutil.rmtree, folder, True)
        return prefs, folder

    def test_leftovers_go_to_the_trash(self):
        _make(os.path.join(self.materials, "AAA1.interface"))
        result = repair.move_aside(self.survey(), "leftovers", guard_session=False)
        self.assertEqual(["materials/AAA1.interface"], result["moved"])
        self.assertTrue(self.trash_holds("materials/AAA1.interface"))
        self.assertFalse(os.path.exists(os.path.join(self.materials, "AAA1.interface")))

    def test_the_folder_s_icon_is_the_system_s_own_file_and_stays(self):
        from amaze import package_file
        from amaze.helpers import hostos
        carrier = os.path.join(self.dir, hostos.FOLDER_ICON_FILE)
        if hostos.is_windows():
            self.skipTest("Windows refuses a file name with a carriage return in it")
        if hostos.is_macos():
            self.assertTrue(hostos.give_folder_icon(self.dir, package_file(
                "ui", "library_folder")), "the folder was given no icon")
            self.assertTrue(os.path.exists(carrier))
            self.assertFalse(hostos.give_folder_icon(self.dir, package_file(
                "ui", "library_folder")), "a folder that carries its icon was given one again")
        else:
            _make(carrier)
        result = repair.move_aside(self.survey(), "unknown", guard_session=False)
        self.assertEqual([], result["moved"])
        self.assertTrue(os.path.exists(carrier))

    def test_on_windows_the_folder_gets_its_icon_and_an_ini_that_names_it(self):
        from unittest import mock
        from amaze import package_file
        from amaze.helpers import hostos
        marked = []
        with mock.patch.object(hostos, "is_windows", lambda: True), mock.patch.object(
                hostos, "_add_attributes", lambda path, bits: marked.append((path, bits)) or True):
            for artwork in ("library_folder", "matx_folder"):
                self.assertTrue(os.path.isfile(package_file("ui", artwork + ".ico")))
            self.assertTrue(hostos.give_folder_icon(self.dir, package_file("ui", "library_folder")))
            ini = os.path.join(self.dir, hostos.WINDOWS_FOLDER_INI)
            with open(ini, "rb") as handle:
                self.assertEqual(b"[.ShellClassInfo]\r\nIconResource=amaze_folder.ico,0\r\n",
                                 handle.read())
            self.assertTrue(os.path.isfile(os.path.join(self.dir, hostos.WINDOWS_FOLDER_ICON)))
            self.assertEqual([(os.path.join(self.dir, hostos.WINDOWS_FOLDER_ICON), 0x2),
                              (ini, 0x2 | 0x4), (self.dir, 0x1)], marked)
            self.assertFalse(hostos.give_folder_icon(self.dir, package_file("ui", "library_folder")),
                             "a folder with a desktop.ini was given another")
        result = repair.move_aside(self.survey(), "unknown", guard_session=False)
        self.assertEqual([], result["moved"], "the icon's two files were treated as unknown ones")

    def test_unknown_files_and_folders_go_to_the_trash(self):
        _make(os.path.join(self.dir, "notes.txt"))
        _make(os.path.join(self.dir, "stuff", "a.bin"))
        result = repair.move_aside(self.survey(), "unknown", guard_session=False)
        self.assertEqual(["notes.txt", "stuff"], sorted(result["moved"]))
        self.assertTrue(self.trash_holds("notes.txt"))
        self.assertTrue(self.trash_holds("stuff/a.bin"))

    def test_stars_on_files_that_are_gone_are_removed(self):
        prefs, folder = self.files_prefs()
        prefs.add_file_folder(folder)
        star = test_support.posix_path(_make(os.path.join(folder, "shot.exr")))    # as stars are stored
        prefs.add_file_favorite(star)
        os.remove(star)
        findings = repair.survey(prefs)
        self.assertIn("This starred file is gone from its folder:\n  %s" % os.path.normpath(star),
                      "\n".join(repair.report_lines(findings)))
        self.assertEqual([star], repair.drop_favorites_of_missing_files(findings,
                                                                        guard_session=False))
        self.assertNotIn(star, prefs.file_favorites)

    def test_a_location_whose_folder_is_gone_is_set_aside(self):
        prefs, folder = self.files_prefs()
        gone = os.path.join(folder, "gone")
        os.makedirs(gone)
        prefs.add_file_folder(gone)
        os.rmdir(gone)
        findings = repair.survey(prefs)
        self.assertIn("This folder in the Files section is not on this computer. Setting it "
                      "aside keeps its comments, icons and favorites, and they come back when "
                      "the folder is added again:", "\n".join(repair.report_lines(findings)))
        done = repair.set_aside_folders(findings, guard_session=False)
        self.assertEqual(1, len(done))
        self.assertNotIn(os.path.normpath(gone),
                         [os.path.normpath(path) for path in prefs.file_folders])

    def test_show_holding_folder_reveals_the_trash(self):
        from amaze.dialogs import repair_dialog
        _make(os.path.join(self.materials, "STRAY1.png"))
        repair.move_aside(self.survey(), "unlisted", guard_session=False)
        findings = self.survey()
        labels, keys = repair_dialog._every_choice(findings, True)
        self.assertIn("holding", keys)
        with mock.patch.object(repair_dialog.pane_files, "reveal") as reveal:
            repair_dialog.act(findings, "holding")
        reveal.assert_called_once_with(findings["holding"]["path"])


def _corrupt(directory: str, name: str = MATERIALS) -> None:
    with open(os.path.join(directory, name), "w", encoding="utf-8") as handle:
        handle.write("{ ruined")


class TheThreeLightsTest(_Library):
    """Errors, Files and Ref: each light's state and count, the line, and whether Repair shows."""

    def lights(self, findings=None) -> dict:
        return library_check.summary(findings or self.survey())

    def files_prefs(self):
        test_support.reset_database_singletons()
        prefs = test_support.fixture_prefs(self)
        folder = test_support.scratch_dir("amaze_check_lights_")
        self.addCleanup(shutil.rmtree, folder, True)
        return prefs, folder

    def test_a_clean_library_is_green_with_nothing_to_repair(self):
        found = self.lights()
        self.assertEqual((library_check.CLEAN, 0), found["lights"][library_check.ERRORS])
        self.assertEqual((library_check.CLEAN, 0), found["lights"][library_check.FILES])
        self.assertEqual(messages.CHECK_NOTHING_TO_REPAIR, found["info"])
        self.assertEqual([], found["lines"])
        self.assertFalse(found["fixable"])

    def test_references_are_not_checked_without_the_files_section(self):
        self.assertEqual((library_check.UNCHECKED, None),
                         self.lights()["lights"][library_check.REFS])

    def test_a_corrupt_database_is_one_error_and_leaves_the_files_unchecked(self):
        _corrupt(self.dir)
        self.asset("ORPHAN1")
        found = self.lights()
        self.assertEqual((library_check.FOUND, 1), found["lights"][library_check.ERRORS])
        self.assertEqual((library_check.UNCHECKED, None), found["lights"][library_check.FILES])
        self.assertEqual("The Materials database is corrupt.", found["info"])
        self.assertEqual(["The Materials database is corrupt."], found["lines"])
        self.assertTrue(found["fixable"], "a rebuild from the assets' files is not offered")

    def test_a_missing_database_is_an_error(self):
        os.remove(os.path.join(self.dir, MATERIALS))
        found = self.lights()
        self.assertEqual((library_check.FOUND, 1), found["lights"][library_check.ERRORS])
        self.assertEqual("The Materials database is missing.", found["info"])

    def test_a_newer_database_is_an_error_nothing_here_fixes(self):
        _write(self.dir, NODES, {"assets": {}, "format": 99})
        found = self.lights()
        self.assertEqual((library_check.FOUND, 1), found["lights"][library_check.ERRORS])
        self.assertEqual("The Nodes database is from a newer Amaze.", found["info"])
        self.assertFalse(found["fixable"])

    def test_a_database_in_use_turns_every_light_amber_and_offers_no_fix(self):
        self.asset("ORPHAN1", {"id": "ORPHAN1", "name": "Slate"})
        with mock.patch.object(guard.Guard, "_waiting", lambda self: True):
            findings = self.survey()
        found = self.lights(findings)
        for part in library_check.PARTS:
            self.assertEqual((library_check.UNCHECKED, None), found["lights"][part], part)
        self.assertEqual("The Library database is in use.", found["info"])
        self.assertEqual([], found["lines"])
        self.assertFalse(found["fixable"])
        self.assertEqual([], library_check.all_fixes(findings))
        before = _read(self.dir, MATERIALS)
        done = library_check.fix_all(findings, guard_session=False)
        self.assertEqual([], library_check.done_lines(done))
        self.assertEqual(before, _read(self.dir, MATERIALS))

    def test_a_folder_that_cannot_be_listed_leaves_the_files_unchecked(self):
        test_support.refuse_listing(self, self.materials)
        found = self.lights()
        self.assertEqual((library_check.UNCHECKED, None), found["lights"][library_check.FILES])
        self.assertEqual("The materials folder cannot be read.", found["info"])
        self.assertFalse(found["fixable"])

    def test_a_row_whose_mat_is_gone(self):
        os.remove(os.path.join(self.materials, "AAA1.mat"))
        found = self.lights()
        self.assertEqual((library_check.FOUND, 1), found["lights"][library_check.FILES])
        self.assertEqual("1 material listed in the database has no files.", found["info"])
        self.assertTrue(found["fixable"])
        self.assertFalse(found["safe"], "removing an entry is not a safe fix")

    def test_files_no_database_lists(self):
        self.asset("NEW1", {"id": "NEW1", "name": "Slate"})
        found = self.lights()
        self.assertEqual((library_check.FOUND, 3), found["lights"][library_check.FILES])
        self.assertEqual("3 files in materials/ are in no database.", found["info"])
        self.assertTrue(found["safe"])

    def test_a_row_with_no_picture_is_not_counted(self):
        os.remove(os.path.join(self.materials, "AAA1.png"))
        found = self.lights()
        self.assertEqual((library_check.CLEAN, 0), found["lights"][library_check.FILES])
        self.assertEqual([], found["lines"])
        self.assertEqual([], found["names"])

    def test_leftovers_unknown_files_and_conflict_copies(self):
        _make(os.path.join(self.materials, "AAA1.interface"))
        _make(os.path.join(self.dir, "notes.txt"))
        _make(os.path.join(self.dir, "stuff", "a.bin"))
        _make(os.path.join(self.materials, "AAA1 2.png"), b"y")
        found = self.lights()
        self.assertEqual((library_check.FOUND, 4), found["lights"][library_check.FILES])
        self.assertEqual(["1 file is left over from Amaze's own work.",
                          "1 file and 1 folder are not known to Amaze.",
                          "1 conflict copy from a sync service."], found["lines"])
        self.assertTrue(found["fixable"])

    def test_the_most_serious_finding_is_the_line(self):
        os.remove(os.path.join(self.materials, "AAA1.mat"))
        _make(os.path.join(self.dir, "notes.txt"))
        found = self.lights()
        self.assertEqual(found["lines"][0], found["info"])
        self.assertIn("has no files", found["lines"][0])

    def test_a_favorite_of_a_file_that_is_gone(self):
        prefs, folder = self.files_prefs()
        prefs.add_file_folder(folder)
        star = _make(os.path.join(folder, "shot.exr"))
        prefs.add_file_favorite(star)
        clean = library_check.lights(repair.survey(prefs))[library_check.REFS]
        self.assertEqual((library_check.CLEAN, 0), clean)
        os.remove(star)
        findings = repair.survey(prefs)
        self.assertEqual((library_check.FOUND, 1),
                         library_check.lights(findings)[library_check.REFS])
        self.assertIn("1 favorite is of a file that is gone.",
                      library_check.finding_lines(findings))
        self.assertIn("favorites", library_check.safe_fixes(findings))

    def test_a_folder_of_the_files_section_that_is_gone(self):
        prefs, folder = self.files_prefs()
        gone = os.path.join(folder, "gone")
        os.makedirs(gone)
        prefs.add_file_folder(gone)
        os.rmdir(gone)
        findings = repair.survey(prefs)
        self.assertEqual((library_check.FOUND, 1),
                         library_check.lights(findings)[library_check.REFS])
        self.assertIn("1 folder in the Files section is gone.",
                      library_check.finding_lines(findings))

    def test_a_drive_that_is_not_connected_leaves_the_references_unchecked(self):
        prefs, folder = self.files_prefs()
        away = os.path.join(folder, "away")
        prefs.add_file_folder(away)
        with mock.patch.object(repair.hostos, "volume_unreachable",
                               lambda path: os.path.normpath(path) == os.path.normpath(away)):
            findings = repair.survey(prefs)
        self.assertEqual((library_check.UNCHECKED, None),
                         library_check.lights(findings)[library_check.REFS])


class _Broken(_Library):
    """The small library with an unlisted pair, a row with no `.mat`, a leftover and unknowns."""

    def setUp(self):
        super().setUp()
        self.asset("NEW1", {"id": "NEW1", "name": "Slate", "categories": ["Roofs"],
                            "renderer": "Karma"})
        os.remove(os.path.join(self.materials, "AAA1.mat"))
        _make(os.path.join(self.materials, "AAA2.interface"))
        _make(os.path.join(self.dir, "notes.txt"))
        _make(os.path.join(self.dir, "stuff", "a.bin"))

    def trashed(self) -> list:
        root = os.path.join(self.dir, "trash")
        return sorted(name for _here, _dirs, names in os.walk(root) for name in names)


class TheTwoFixesTest(_Broken):
    """Fix Safe only adds and tidies; Fix All also removes, trashes and restores a database."""

    def test_fix_safe_recovers_and_trashes_removes_and_replaces_nothing(self):
        with mock.patch.object(guard.Guard, "restore") as restore, \
                mock.patch.object(guard.Change, "replace") as replace, \
                mock.patch.object(guard.Change, "trash") as trash:
            done = library_check.fix_safe(self.survey(), guard_session=False)
        self.assertEqual(["1 material added to the database."], library_check.done_lines(done))
        stored = _read(self.dir, MATERIALS)
        self.assertEqual("Slate", stored["assets"]["NEW1"]["name"])
        self.assertIn("AAA1", stored["assets"], "Fix Safe removed an entry")
        self.assertEqual([], self.trashed(), "Fix Safe moved something to the trash")
        for kept in ("materials/AAA2.interface", "notes.txt", "stuff/a.bin", "materials/AAA1.png"):
            self.assertTrue(os.path.exists(os.path.join(self.dir, *kept.split("/"))), kept)
        for step in (restore, replace, trash):
            step.assert_not_called()

    def test_fix_all_with_nothing_confirmed_trashes_only_what_amaze_wrote(self):
        done = library_check.fix_all(self.survey(), guard_session=False)
        self.assertEqual(["1 material added to the database.", "1 file moved to the trash."],
                         library_check.done_lines(done))
        self.assertEqual(["AAA2.interface"], self.trashed())
        self.assertIn("AAA1", _read(self.dir, MATERIALS)["assets"], "an unconfirmed row was removed")
        for kept in ("notes.txt", "stuff/a.bin", "materials/AAA1.png", "materials/AAA1.json"):
            self.assertTrue(os.path.exists(os.path.join(self.dir, *kept.split("/"))), kept)

    def test_what_is_confirmed_is_named_one_per_line(self):
        findings = self.survey()
        found = library_check.confirmable(findings)
        _make(os.path.join(self.materials, "LONE7.mat"))
        findings = self.survey()
        found = library_check.confirmable(findings)
        self.assertEqual(["Materials: Brick", "materials/LONE7.mat", "notes.txt", "stuff/"],
                         library_check.confirmable_names(findings, found))

    def test_a_file_that_appears_after_the_confirm_is_not_trashed(self):
        findings = self.survey()
        confirmed = library_check.confirmable(findings)
        _make(os.path.join(self.dir, "later.txt"))
        library_check.fix_all(findings, guard_session=False, confirmed=confirmed)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "later.txt")),
                        "a file nobody was shown went to the trash")
        self.assertIn("notes.txt", self.trashed())

    def test_a_file_in_the_import_folder_is_the_users_whatever_its_name(self):
        lock = _make(os.path.join(self.dir, "import", "project", "yarn.lock"))
        os.utime(lock, (1_700_000_000, 1_700_000_000))
        findings = self.survey()
        self.assertEqual([], [entry[0] for entry in findings["leftovers"]
                              if entry[0].startswith("import/")])
        library_check.fix_all(findings, guard_session=False,
                              confirmed=library_check.confirmable(findings))
        self.assertTrue(os.path.exists(lock))

    def test_fix_all_also_removes_the_entry_and_trashes_the_leftovers(self):
        findings = self.survey()
        done = library_check.fix_all(findings, guard_session=False,
                                     confirmed=library_check.confirmable(findings))
        self.assertEqual(["1 material added to the database.",
                          "1 material removed from the database.",
                          "4 files and 1 folder moved to the trash."],
                         library_check.done_lines(done))
        stored = _read(self.dir, MATERIALS)
        self.assertEqual({"AAA2", "NEW1"}, set(stored["assets"]))
        self.assertEqual(["AAA1.json", "AAA1.png", "AAA2.interface", "a.bin", "notes.txt"],
                         self.trashed())
        self.assertFalse(os.path.exists(os.path.join(self.dir, "stuff")))
        after = library_check.summary(self.survey())
        self.assertEqual((library_check.CLEAN, 0), after["lights"][library_check.FILES])
        self.assertFalse(after["fixable"])

    def test_fix_all_restores_the_newest_backup_of_a_corrupt_database(self):
        test_support.backup_now(self.dir, MATERIALS)
        _corrupt(self.dir)
        done = library_check.fix_all(self.survey(), guard_session=False)
        self.assertEqual([MATERIALS], done["restored"])
        self.assertEqual([], done["rebuilt"])
        self.assertIn("1 database restored from its backup.", library_check.done_lines(done))
        self.assertEqual({"AAA1", "AAA2", "NEW1"}, set(_read(self.dir, MATERIALS)["assets"]),
                         "NEW1 was not recovered, or AAA1 was removed with no confirm")

    def test_fix_all_restores_a_missing_database(self):
        test_support.backup_now(self.dir, MATERIALS)
        os.remove(os.path.join(self.dir, MATERIALS))
        done = library_check.fix_all(self.survey(), guard_session=False)
        self.assertEqual([MATERIALS], done["restored"])
        self.assertIn("AAA2", _read(self.dir, MATERIALS)["assets"])

    def test_fix_all_rebuilds_a_corrupt_database_that_has_no_backup(self):
        _corrupt(self.dir)
        done = library_check.fix_all(self.survey(), guard_session=False)
        self.assertEqual([MATERIALS], done["rebuilt"])
        self.assertIn("1 database rebuilt from the assets' own files.",
                      library_check.done_lines(done))
        self.assertEqual({"AAA1", "AAA2", "NEW1"}, set(_read(self.dir, MATERIALS)["assets"]))

    def test_a_database_with_no_backup_and_no_asset_files_starts_empty(self):
        for name in (library_files.COLORS, library_files.FILES):
            _write(self.dir, name, {"assets": {}} if name == library_files.COLORS else {})
        master = _read(self.dir, library_files.MASTER)
        master["manifest"].update({library_files.COLORS: {"by": ""}, library_files.FILES: {"by": ""}})
        _write(self.dir, library_files.MASTER, master)
        _corrupt(self.dir, library_files.COLORS)
        os.remove(os.path.join(self.dir, library_files.FILES))
        found = library_check.summary(self.survey())
        self.assertIn("The Colors database has no backup. Fix All starts it empty.", found["lines"])
        self.assertTrue(found["fixable"])
        done = library_check.fix_all(self.survey(), guard_session=False)
        self.assertEqual([library_files.COLORS, library_files.FILES], done["emptied"])
        self.assertIn("2 databases start empty.", library_check.done_lines(done))
        held = guard.Guard(self.dir)
        for name in (library_files.COLORS, library_files.FILES):
            self.assertEqual(guard.FINE, held.read(name).verdict, name)
        kept = [name for name in os.listdir(os.path.join(self.dir, "backup"))
                if name.startswith(library_files.COLORS + guard.UNREADABLE_MARK)]
        self.assertEqual(1, len(kept), "the corrupt file was not kept in backup/")

    def test_a_library_database_with_no_backup_starts_empty_and_lists_what_is_here(self):
        _corrupt(self.dir, library_files.MASTER)
        done = library_check.fix_all(self.survey(), guard_session=False)
        self.assertEqual([library_files.MASTER], done["emptied"])
        master = _read(self.dir, library_files.MASTER)
        self.assertEqual([MATERIALS], sorted(master["manifest"]))
        self.assertEqual(library_check.repair.library_policy.LIBRARY_VERSION,
                         master["policy"]["library"]["version"])
        held = guard.Guard(self.dir)
        change = held.change("u1")
        change.put(held.read(NODES).ticket, {"assets": {}})
        change.commit()
        self.assertEqual(guard.FINE, held.read(NODES).verdict)

    def test_fix_safe_leaves_a_corrupt_database_as_it_is(self):
        _corrupt(self.dir)
        done = library_check.fix_safe(self.survey(), guard_session=False)
        self.assertEqual([], library_check.done_lines(done))
        with open(os.path.join(self.dir, MATERIALS), encoding="utf-8") as handle:
            self.assertEqual("{ ruined", handle.read())


class TheRepairDialogTest(_Broken):
    """The Repair dialog through a fake `hou.ui`: its text, its buttons, what each one does."""

    def run_dialog(self, pick: int, findings=None) -> list:
        from amaze.dialogs import repair_dialog
        shown = []

        def display(text, **kwargs):
            shown.append((text, kwargs))
            return pick if len(shown) == 1 else (self.second if len(shown) == 2 else 0)

        changed = []
        with mock.patch.object(repair_dialog.hou, "ui",
                               mock.Mock(displayMessage=display), create=True):
            self.landed = repair_dialog.repair_found(
                findings or self.survey(), guard=False, changed=lambda: changed.append(1))
        self.changed = len(changed)
        return shown

    def test_the_text_and_the_buttons_with_cancel_the_default_and_the_close(self):
        shown = self.run_dialog(2)
        text, asked = shown[0]
        self.assertEqual(
            "Check Library found:\n\n"
            "1 material listed in the database has no files.\n"
            "3 files in materials/ are in no database.\n"
            "1 file is left over from Amaze's own work.\n"
            "1 file and 1 folder are not known to Amaze.", text)
        self.assertEqual(("Fix All", "Fix Safe", "Cancel"), tuple(asked["buttons"]))
        self.assertEqual((2, 2), (asked["default_choice"], asked["close_choice"]))
        names = asked["details"].split("\n")
        self.assertIn("Materials: " + self.survey()["missing_files"][MATERIALS][0][1], names)
        self.assertEqual(7, len(names), "the dialog does not name each thing its lines count")
        self.assertEqual("Amaze", asked["title"])
        self.assertEqual(1, len(shown), "Cancel showed a second message")
        self.assertEqual((False, 0), (self.landed, self.changed))
        self.assertIn("AAA1", _read(self.dir, MATERIALS)["assets"])
        self.assertEqual([], self.trashed())

    def test_fix_safe_reports_what_it_did_as_counts(self):
        shown = self.run_dialog(1)
        self.assertEqual(["1 material added to the database."],
                         [text for text, _asked in shown[1:]])
        self.assertEqual("Amaze", shown[1][1]["title"])
        self.assertEqual((True, 1), (self.landed, self.changed))
        self.assertEqual([], self.trashed())

    second = 0    # the button the fake picks in the second message: Move to Trash

    def test_fix_all_names_what_goes_to_the_trash_and_reports_what_it_did_as_counts(self):
        shown = self.run_dialog(0)
        text, asked = shown[1]
        self.assertEqual(messages.CONFIRM_FIX_ALL_TRASH, text)
        self.assertEqual(("Move to Trash", "Skip These", "Cancel"), tuple(asked["buttons"]))
        self.assertEqual((2, 2), (asked["default_choice"], asked["close_choice"]))
        self.assertEqual(["Materials: Brick", "notes.txt", "stuff/"], asked["details"].split("\n"))
        self.assertEqual(["1 material added to the database.\n"
                          "1 material removed from the database.\n"
                          "4 files and 1 folder moved to the trash."],
                         [text for text, _asked in shown[2:]])
        self.assertNotIn("AAA1", _read(self.dir, MATERIALS)["assets"])

    def test_skip_these_fixes_the_rest_and_leaves_what_was_named(self):
        self.second = 1
        shown = self.run_dialog(0)
        self.assertEqual(["1 material added to the database.\n1 file moved to the trash."],
                         [text for text, _asked in shown[2:]])
        self.assertIn("AAA1", _read(self.dir, MATERIALS)["assets"])
        self.assertEqual(["AAA2.interface"], self.trashed())

    def test_cancel_in_the_second_message_changes_nothing(self):
        self.second = 2
        shown = self.run_dialog(0)
        self.assertEqual(2, len(shown))
        self.assertEqual((False, 0), (self.landed, self.changed))
        self.assertEqual([], self.trashed())
        self.assertNotIn("NEW1", _read(self.dir, MATERIALS)["assets"])

    def test_with_nothing_safe_to_do_fix_safe_is_not_offered(self):
        os.remove(os.path.join(self.materials, "NEW1.mat"))
        os.remove(os.path.join(self.materials, "NEW1.json"))
        shown = self.run_dialog(1)
        self.assertEqual(("Fix All", "Cancel"), tuple(shown[0][1]["buttons"]))
        self.assertEqual(1, len(shown))


class EachRepairTestFailsWhenItsStepIsPatchedOutTest(unittest.TestCase):
    """Each TheTwoFixesTest test fails when the step it depends on is patched to do nothing."""

    PATCHED_STEPS = (
        ("test_fix_safe_recovers_and_trashes_removes_and_replaces_nothing",
         "amaze.core.guard.Change.put", lambda *_a, **_k: None),
        ("test_fix_all_also_removes_the_entry_and_trashes_the_leftovers",
         "amaze.core.guard.Change.trash", lambda *_a, **_k: None),
        ("test_fix_all_also_removes_the_entry_and_trashes_the_leftovers",
         "amaze.core.repair.drop_rows_without_files", lambda *_a, **_k: {}),
        ("test_fix_all_restores_the_newest_backup_of_a_corrupt_database",
         "amaze.core.guard.Guard.restore", lambda *_a, **_k: None),
        ("test_fix_all_restores_a_missing_database",
         "amaze.core.guard.Guard.restore", lambda *_a, **_k: None),
        ("test_fix_all_rebuilds_a_corrupt_database_that_has_no_backup",
         "amaze.core.guard.Change.replace", lambda *_a, **_k: None),
    )

    def test_every_repair_test_fails_with_its_step_patched_out(self):
        for name, target, broken in self.PATCHED_STEPS:
            with self.subTest(name=name, target=target):
                result = unittest.TestResult()
                with mock.patch(target, broken):
                    TheTwoFixesTest(name).run(result)
                self.assertTrue(result.failures or result.errors,
                                "%s passed with %s patched out" % (name, target))


class EachFixTestFailsWhenItsGuardStepIsPatchedOutTest(unittest.TestCase):
    """Each fix's test fails when the guard step it depends on is patched to do nothing."""

    PATCHED_STEPS = (
        ("test_restore_a_backup_keeps_the_database_you_have_as_an_undo_copy",
         "amaze.core.guard.Guard.restore", lambda *_a, **_k: None),
        ("test_orphaned_files_go_to_the_librarys_trash",
         "amaze.core.guard.Change.trash", lambda *_a, **_k: None),
        ("test_orphaned_materials_are_recovered_from_their_metadata",
         "amaze.core.guard.Change.put", lambda *_a, **_k: None),
        ("test_each_folder_s_pairs_are_recovered_into_its_own_section",
         "amaze.core.guard.Change.take", lambda *_a, **_k: None),
        ("test_each_folder_s_pairs_are_recovered_into_its_own_section",
         "amaze.core.guard.Change.put", lambda *_a, **_k: None),
        ("test_a_lost_database_is_rebuilt_from_each_assets_metadata",
         "amaze.core.guard.Change.replace", lambda *_a, **_k: None),
        ("test_rows_with_no_category_are_put_in_uncategorized",
         "amaze.core.guard.Change.put", lambda *_a, **_k: None),
    )

    def test_every_fix_test_fails_with_its_step_patched_out(self):
        for name, target, broken in self.PATCHED_STEPS:
            with self.subTest(name=name):
                result = unittest.TestResult()
                with mock.patch(target, broken):
                    TheFixesActThroughTheGuardTest(name).run(result)
                self.assertTrue(result.failures or result.errors,
                                "%s passed with %s patched out" % (name, target))


if __name__ == "__main__":
    unittest.main()
