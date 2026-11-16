"""Check Library 2.0: the guard's judgement in the report, and every fix acting through the guard."""

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

from amaze.core import asset_record, guard, library_files, repair  # noqa: E402
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
    """A small 2.0 library: two materials with their files and metadata, no session holding it."""

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


class TheReportIsTheGuardsJudgementTest(_Library):

    def test_a_corrupt_database_is_named_and_holds_every_move_back(self):
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
            repair.move_aside(findings, "unlisted", guard=False)
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
        done = repair.put_back(findings, filename, backup, guard=False)
        self.assertEqual({"AAA1", "AAA2"}, set(_read(self.dir, MATERIALS)["assets"]))
        self.assertTrue(done["undo"].endswith(guard.UNDO_TAIL), "nothing kept to undo")

    def test_orphaned_files_go_to_the_librarys_trash(self):
        with open(os.path.join(self.materials, "STRAY1.png"), "wb") as handle:
            handle.write(b"x")
        findings = self.survey()
        self.assertEqual(["STRAY1.png"], findings["unaccounted"]["materials/"])
        result = repair.move_aside(findings, "unlisted", guard=False)
        self.assertEqual(["STRAY1.png"], result["moved"])
        self.assertFalse(os.path.exists(os.path.join(self.materials, "STRAY1.png")))
        self.assertTrue(self.trash_holds("materials/STRAY1.png"))

    def test_orphaned_materials_are_recovered_from_their_metadata(self):
        self.asset("NEW1", {"id": "NEW1", "name": "Slate", "categories": ["Roofs"],
                            "renderer": "Karma"})
        findings = self.survey()
        self.assertEqual({MATERIALS: ["NEW1"]}, repair.recoverable(findings))
        result = repair.recover(findings, guard=False)
        self.assertEqual(["NEW1"], result[MATERIALS]["added"])
        stored = _read(self.dir, MATERIALS)
        self.assertEqual("Slate", stored["assets"]["NEW1"]["name"])
        self.assertIn("Roofs", stored["categories"])

    def test_each_folder_s_pairs_are_recovered_into_its_own_section(self):
        """No question asked: the materials folder's pairs go to Materials, the nodes folder's to Nodes."""
        nodes = os.path.join(self.dir, "nodes")
        long_id = "ABCDEF0123456789ABCDEF0123456789"
        self.asset(long_id, folder=nodes)
        self.asset("RIG1", {"id": "RIG1", "name": "Rig", "renderer": "Karma"}, nodes)
        os.rename(os.path.join(nodes, "RIG1.png"), os.path.join(self.materials, "RIG1.png"))
        self.asset("MAT9")
        findings = self.survey()
        self.assertEqual({MATERIALS: ["MAT9"], NODES: [long_id, "RIG1"]},
                         repair.recoverable(findings))
        result = repair.recover(findings, guard=False)
        self.assertEqual([long_id, "RIG1"], sorted(result[NODES]["added"]))
        self.assertEqual(["MAT9"], result[MATERIALS]["added"])
        node_rows = _read(self.dir, NODES)["assets"]
        self.assertEqual("Recovered " + long_id, node_rows[long_id]["name"],
                         "an asset whose metadata cannot be read is not named by its whole id")
        self.assertEqual("Rig", node_rows["RIG1"]["name"])
        self.assertEqual("Recovered MAT9", _read(self.dir, MATERIALS)["assets"]["MAT9"]["name"])
        self.assertTrue(os.path.exists(os.path.join(nodes, "RIG1.png")),
                        "a file in the other folder did not move home with the row")
        self.assertFalse(os.path.exists(os.path.join(self.materials, "RIG1.png")))

    def test_a_lost_database_is_rebuilt_from_each_assets_metadata(self):
        for asset_id, name in (("AAA1", "Brick"), ("AAA2", "Oak")):
            self.asset(asset_id, {"id": asset_id, "name": name, "categories": ["Walls"],
                                  "renderer": "Karma"})
        with open(os.path.join(self.dir, MATERIALS), "w", encoding="utf-8") as handle:
            handle.write("{ ruined")
        done = repair.rebuild(self.dir, MATERIALS, guard=False)
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
        done = repair.rescue_uncategorised(findings, guard=False)
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
        built = repair.rebuild_from_stamps(self.dir, MATERIALS)
        self.assertEqual({"AAA1", "AAA2", "NEW4"}, set(built["assets"]))
        self.assertEqual({"NODE3"}, set(repair.rebuild_from_stamps(self.dir, NODES)["assets"]))


def _make(path: str, data: bytes = b"x", age_s: float = 0) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    if age_s:
        when = time.time() - age_s
        os.utime(path, (when, when))
    return path


class EverySentenceOfTheReportTest(_Library):
    """One test per sentence the report can say, each set up so that sentence is true."""

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
        if hasattr(os, "getuid") and os.getuid() == 0:
            self.skipTest("root lists every folder")
        os.chmod(self.materials, 0)
        self.addCleanup(os.chmod, self.materials, 0o755)
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
                      "Thumbnail ▸ Render Image when convenient", text)
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
        repair.move_aside(self.survey(), "unlisted", guard=False)
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
                      "and 1 node (Rig) in the Nodes database: each goes by the folder its "
                      "files are in.", text)
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


class TheFixesKeepTheirWordTest(_Library):
    """The fixes the first fix tests leave out: leftovers, unknown files, stars, locations, trash."""

    def files_prefs(self):
        test_support.reset_database_singletons()
        prefs = test_support.fixture_prefs(self)
        folder = test_support.scratch_dir("amaze_check_fix_")
        self.addCleanup(shutil.rmtree, folder, True)
        return prefs, folder

    def test_leftovers_go_to_the_trash(self):
        _make(os.path.join(self.materials, "AAA1.interface"))
        result = repair.move_aside(self.survey(), "leftovers", guard=False)
        self.assertEqual(["materials/AAA1.interface"], result["moved"])
        self.assertTrue(self.trash_holds("materials/AAA1.interface"))
        self.assertFalse(os.path.exists(os.path.join(self.materials, "AAA1.interface")))

    def test_unknown_files_and_folders_go_to_the_trash(self):
        _make(os.path.join(self.dir, "notes.txt"))
        _make(os.path.join(self.dir, "stuff", "a.bin"))
        result = repair.move_aside(self.survey(), "unknown", guard=False)
        self.assertEqual(["notes.txt", "stuff"], sorted(result["moved"]))
        self.assertTrue(self.trash_holds("notes.txt"))
        self.assertTrue(self.trash_holds("stuff/a.bin"))

    def test_stars_on_files_that_are_gone_are_removed(self):
        prefs, folder = self.files_prefs()
        prefs.add_file_folder(folder)
        star = _make(os.path.join(folder, "shot.exr"))
        prefs.add_file_favorite(star)
        os.remove(star)
        findings = repair.survey(prefs)
        self.assertIn("This starred file is gone from its folder:\n  %s" % os.path.normpath(star),
                      "\n".join(repair.report_lines(findings)))
        self.assertEqual([star], repair.drop_dead_stars(findings, guard=False))
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
        done = repair.set_aside_folders(findings, guard=False)
        self.assertEqual(1, len(done))
        self.assertNotIn(os.path.normpath(gone),
                         [os.path.normpath(path) for path in prefs.file_folders])

    def test_show_holding_folder_reveals_the_trash(self):
        from amaze.dialogs import repair_dialog
        _make(os.path.join(self.materials, "STRAY1.png"))
        repair.move_aside(self.survey(), "unlisted", guard=False)
        findings = self.survey()
        labels, keys = repair_dialog._every_choice(findings, True)
        self.assertIn("holding", keys)
        with mock.patch.object(repair_dialog.ui_helpers, "reveal") as reveal:
            repair_dialog.act(findings, "holding")
        reveal.assert_called_once_with(findings["holding"]["path"])


class EachFixGoesRedWhenItIsBrokenTest(unittest.TestCase):
    """Sabotage: each fix's test fails when the guard step it stands on does nothing."""

    SABOTAGES = (
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

    def test_every_fix_test_catches_its_sabotage(self):
        for name, target, broken in self.SABOTAGES:
            with self.subTest(name=name):
                result = unittest.TestResult()
                with mock.patch(target, broken):
                    TheFixesActThroughTheGuardTest(name).run(result)
                self.assertTrue(result.failures or result.errors,
                                "%s stayed green with %s broken" % (name, target))


if __name__ == "__main__":
    unittest.main()
