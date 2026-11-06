"""Check Library's engine: one walk, one naming convention, and moves that never delete."""

import ast
import builtins
import json
import os
import shutil
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from amaze.core import database, debug, keyed_store, library_files, library_policy  # noqa: E402
from amaze.core import material, quarantine, renderers, repair  # noqa: E402
from amaze.helpers import hostos                           # noqa: E402
from amaze.helpers import restore as restore_lib           # noqa: E402
from amaze.tests import test_support                       # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
AUDIT = os.path.join(REPO, "tools", "library-audit.py")
HOUR = 60 * 60


class _Library(unittest.TestCase):
    """A private copy of the fixture library, its odd legacy row taken out so it starts healthy."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.dir = self.prefs.dir
        self.mat_dir = os.path.join(self.dir, "mat")
        self.img_dir = os.path.join(self.dir, "img")
        self.index = os.path.join(self.dir, "library.json")
        document = self._read(self.index)
        document["assets"] = [row for row in document["assets"]
                              if str(row.get("id")) != "-1"]
        self._write(self.index, document)
        self.first_id = str(document["assets"][0]["id"])

    def _read(self, path):
        with open(path, encoding="utf-8-sig") as handle:
            return json.load(handle)

    def _write(self, path, document):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=4)

    def _file(self, relative, text="x", hours_old=0.0):
        path = os.path.join(self.dir, *relative.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        if hours_old:
            when = time.time() - hours_old * HOUR
            os.utime(path, (when, when))
        return path

    def _survey(self):
        return repair.survey(self.dir, self.prefs.asset_dir, self.prefs.img_dir)

    def _leftovers(self, findings):
        return sorted(entry[0] for entry in findings["leftovers"])

    def _held(self, findings):
        return {entry[0]: entry for entry in findings["held_back"]}

    def _holding_has(self, relative):
        root = quarantine.quarantine_folder(self.dir)
        return os.path.exists(os.path.join(root, *relative.split("/")))


class TheConventionHasOneHomeTest(unittest.TestCase):
    """`core/library_files.py` is the one statement; everything else asks it."""

    def test_it_imports_nothing_from_the_package(self):
        with open(library_files.__file__, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        self.assertEqual([], [name for name in imported if name.startswith("amaze")],
                         "the audit tool loads this file where Houdini will not start")

    def test_its_lists_are_the_package_s_lists(self):
        self.assertEqual(set(database.DATABASES), set(library_files.LISTS))
        self.assertEqual(set(keyed_store.filenames()), set(library_files.SIDE_TABLES))
        self.assertEqual(library_policy.FILENAME, library_files.POLICY)
        self.assertEqual(restore_lib.TIERS, library_files.TIERS)
        self.assertEqual(restore_lib.UNDO_TIER, library_files.UNDO_TIER)
        self.assertEqual(repair.ASSET_SIDECARS, library_files.ASSET_SUFFIXES)
        markers = {marker for markers in database._EXISTED_MARKERS.values()
                   for marker in markers}
        self.assertEqual(markers, set(library_files.MARKERS))

    def test_the_package_s_asset_id_answers_through_it(self):
        with patch.object(library_files, "asset_id", return_value="ASKED") as asked:
            self.assertEqual("ASKED", database.asset_id_for_file("x.mat", (".mat",)))
        asked.assert_called_once()

    def test_every_name_in_the_table_is_known(self):
        known = ("library.json", "notes.json", "policy.json", "users.json",
                 "library.json.bak-1", "cops.json.bak-first",
                 "code.json.unreadable", "code.json.unreadable.2",
                 "library.json.bak-before-restore-20261106-101010",
                 "library.json.bak-before-restore-20261106-101010-2",
                 ".amaze_gradient_seed_v1", ".assetlib_code_starter_v1",
                 "mat/abc.mat", "mat/abc.interface", "mat/abc.builder.json",
                 "mat/abc.stamp.json", "mat/abc_cop.mat",
                 "mat/versions/abc/Writer-3.mat", "mat/versions/abc/3.png",
                 "mat/versions/abc/2.builder.json", "mat/versions/abc/versions.json",
                 "mat/versions/abc/versions.json.bak-2",
                 "img/abc.png", "img/abc_icon.png",
                 "captures/abc.png", "captures/file_" + "0a" * 20 + ".png",
                 "code/versions/abc/4.txt", "code/versions/abc/versions.json",
                 "matX/pack/tex.exr")
        for relative in known:
            kind, _detail = library_files.classify(relative)
            self.assertIn(kind, library_files.KNOWN, relative)
        for relative in ("mat", "img", "captures", "mat/versions", "mat/versions/abc",
                         "code/versions/abc", "matX/pack"):
            self.assertEqual(library_files.FOLDER,
                             library_files.classify(relative, is_dir=True)[0], relative)

    def test_the_rest_is_named_by_what_it_is(self):
        for relative, kind in (
                ("img/140024152983962990.png.lock", library_files.SCRATCH),
                ("mat/abc.mat.x1y2.writing", library_files.SCRATCH),
                ("img/abc.png.x1y2.rendering.png", library_files.SCRATCH),
                ("matX/pack/half.tmp", library_files.SCRATCH),
                ("mat/abc.mat.pre-adopt", library_files.PRE_ADOPT_COPY),
                ("mat/abc.builder.json.pre-adopt", library_files.PRE_ADOPT_COPY),
                ("notes.json 2.bak-3", library_files.DUPLICATE),
                ("library 2.json", library_files.DUPLICATE),
                ("mat/abc 2.mat", library_files.DUPLICATE),
                ("mat/abc 2.stamp.json", library_files.DUPLICATE),
                ("stray.txt", library_files.UNKNOWN),
                ("mat/notes.txt", library_files.UNKNOWN),
                ("mat/library (conflicted copy).mat", library_files.UNKNOWN),
                ("img/abc.jpg", library_files.UNKNOWN),
                (".DS_Store", library_files.OS_NOISE_KIND),
                ("mat/._abc.mat", library_files.OS_NOISE_KIND)):
            self.assertEqual(kind, library_files.classify(relative)[0], relative)
        self.assertEqual("notes.json.bak-3",
                         library_files.classify("notes.json 2.bak-3")[1])
        self.assertEqual("mat/abc.stamp.json",
                         library_files.classify("mat/abc 2.stamp.json")[1])
        self.assertEqual((library_files.UNKNOWN, "folder"),
                         library_files.classify("mat/backup-2026-09-04", is_dir=True))


class DuplicatesTest(_Library):
    """A sync service's second copy: a copy of a copy goes, a second version of a live file stays."""

    def test_a_duplicate_backup_beside_its_original_is_moved_aside(self):
        self._file("notes.json.bak-3", '{"pages": {}}')
        self._file("notes.json 2.bak-3", '{"pages": {"a": 1}}')
        findings = self._survey()
        self.assertIn("notes.json 2.bak-3", self._leftovers(findings))
        repair.move_aside(findings, "leftovers")
        self.assertFalse(os.path.exists(os.path.join(self.dir, "notes.json 2.bak-3")))
        self.assertTrue(os.path.exists(os.path.join(self.dir, "notes.json.bak-3")),
                        "the original was moved with its duplicate")
        self.assertTrue(self._holding_has("notes.json 2.bak-3"),
                        "moved means recoverable: it is not in the holding folder")

    def test_a_live_list_s_duplicate_goes_only_when_its_bytes_are_the_same(self):
        with open(self.index, "rb") as handle:
            same = handle.read()
        with open(os.path.join(self.dir, "library 2.json"), "wb") as handle:
            handle.write(same)
        self._file("cops 2.json", '{"assets": [{"id": "X"}]}')
        self._file("cops.json", '{"categories": ["_All"], "assets": []}')
        findings = self._survey()
        self.assertIn("library 2.json", self._leftovers(findings))
        self.assertNotIn("cops 2.json", self._leftovers(findings),
                         "a second version of a list was offered to be swept")
        held = self._held(findings)
        self.assertEqual("cops.json", held["cops 2.json"][1])
        repair.move_aside(findings, "leftovers")
        self.assertFalse(os.path.exists(os.path.join(self.dir, "library 2.json")))
        self.assertTrue(os.path.exists(os.path.join(self.dir, "cops 2.json")),
                        "a duplicate whose bytes differ was moved")
        text = "\n".join(repair.report_lines(findings))
        self.assertIn("`cops 2.json`", text)
        self.assertIn("`cops.json`", text)

    def test_a_lone_duplicate_is_named_and_left(self):
        self._file("mat/LONEASSET1 2.mat", "net")
        findings = self._survey()
        self.assertEqual([], self._leftovers(findings))
        self.assertIn("mat/LONEASSET1 2.mat", self._held(findings))
        repair.move_aside(findings, "leftovers")
        self.assertTrue(os.path.exists(os.path.join(self.mat_dir, "LONEASSET1 2.mat")))
        self.assertIn("`mat/LONEASSET1 2.mat`", "\n".join(repair.report_lines(findings)))

    def test_a_duplicate_that_changed_after_the_check_is_not_moved(self):
        with open(self.index, "rb") as handle:
            same = handle.read()
        twin = os.path.join(self.dir, "library 2.json")
        with open(twin, "wb") as handle:
            handle.write(same)
        findings = self._survey()
        with open(twin, "ab") as handle:
            handle.write(b"\n")
        result = repair.move_aside(findings, "leftovers")
        self.assertTrue(os.path.exists(twin), "it was moved on what the check saw, not what is there")
        self.assertIn("library 2.json", result["failed"])


class LeftoversTest(_Library):
    """What Amaze made and no longer needs goes by default; anything else waits for its own button."""

    def test_an_old_lock_is_moved_and_a_fresh_one_is_not(self):
        old = self._file("img/%s.png.lock" % self.first_id, hours_old=2)
        fresh = self._file("img/OTHER1.png.lock")
        findings = self._survey()
        self.assertEqual(["img/%s.png.lock" % self.first_id], self._leftovers(findings),
                         "a fresh scratch may be another session's live write")
        repair.move_aside(findings, "leftovers")
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(fresh))

    def test_a_pre_adopt_backup_is_moved(self):
        path = self._file("mat/%s.mat.pre-adopt" % self.first_id)
        findings = self._survey()
        self.assertIn("mat/%s.mat.pre-adopt" % self.first_id, self._leftovers(findings))
        repair.move_aside(findings, "leftovers")
        self.assertFalse(os.path.exists(path))
        self.assertTrue(self._holding_has("mat/%s.mat.pre-adopt" % self.first_id))

    def test_an_unknown_folder_is_named_and_left_until_its_own_sweep(self):
        for n in range(3):
            self._file("mat/backup-2026-09-04/%d.mat" % n, "abc")
        stray = self._file("img/comments.txt", "hello")
        findings = self._survey()
        folders = {entry[0]: entry for entry in findings["unknown_folders"]}
        self.assertEqual(3, folders["mat/backup-2026-09-04"][1], "its file count")
        self.assertEqual(9, folders["mat/backup-2026-09-04"][2], "its size")
        self.assertEqual(["img/comments.txt"], [entry[0] for entry in findings["unknown"]])
        text = "\n".join(repair.report_lines(findings))
        self.assertIn("`mat/backup-2026-09-04/`", text)
        self.assertIn("`img/comments.txt`", text)
        repair.move_aside(findings, "leftovers")
        repair.move_aside(findings, "unlisted")
        self.assertTrue(os.path.isdir(os.path.join(self.mat_dir, "backup-2026-09-04")),
                        "an unknown folder went with the default sweep")
        self.assertTrue(os.path.exists(stray))
        result = repair.move_aside(findings, "unknown")
        self.assertFalse(os.path.exists(os.path.join(self.mat_dir, "backup-2026-09-04")))
        self.assertFalse(os.path.exists(stray))
        self.assertTrue(self._holding_has("mat/backup-2026-09-04/2.mat"))
        self.assertEqual([], result["failed"])

    def test_a_capture_no_list_knows_is_unlisted(self):
        self._file("captures/NOBODYS1.png")
        self._file("captures/%s.png" % self.first_id)
        self._file("captures/file_%s.png" % ("ab" * 20))
        findings = self._survey()
        self.assertEqual(["NOBODYS1.png"], findings["unaccounted"]["captures/"])

    def test_the_os_s_own_files_are_neither_named_nor_moved(self):
        self._file(".DS_Store")
        self._file("mat/._x.mat")
        findings = self._survey()
        self.assertEqual([], findings["unknown"])
        self.assertEqual([], findings["leftovers"])


class OneWalkTest(_Library):
    """Every folder listed once, and a stamp opened only where a list lost its pair."""

    def test_each_folder_is_listed_once(self):
        self._file("mat/versions/%s/1.mat" % self.first_id)
        self._file("captures/%s.png" % self.first_id)
        listed = []
        real_scandir, real_listdir = os.scandir, os.listdir
        import glob as glob_mod
        real_glob = glob_mod.glob
        library = os.path.realpath(self.dir)

        def note(path):
            path = os.path.realpath(str(path) or ".")
            if path.startswith(library):
                listed.append(os.path.relpath(path, library))

        def scandir(path="."):
            note(path)
            return real_scandir(path)

        def listdir(path="."):
            note(path)
            return real_listdir(path)

        def glob(pattern, *args, **kwargs):
            note(os.path.dirname(pattern))
            return real_glob(pattern, *args, **kwargs)

        with patch.object(os, "scandir", scandir), patch.object(os, "listdir", listdir), \
                patch.object(glob_mod, "glob", glob):
            self._survey()
        twice = sorted({path for path in listed if listed.count(path) > 1})
        self.assertEqual([], twice, "listed more than once: %s" % twice)
        self.assertIn("mat", listed)

    def test_a_stamp_is_read_only_for_an_unlisted_pair(self):
        for asset_id in ("LISTEDA1", "LISTEDA2"):
            self._file("mat/%s.stamp.json" % asset_id, json.dumps({"id": asset_id}))
        document = self._read(self.index)
        document["assets"] += [{"id": "LISTEDA1", "name": "a", "categories": ["x"]},
                               {"id": "LISTEDA2", "name": "b", "categories": ["x"]}]
        self._write(self.index, document)
        for suffix in (".mat", ".interface"):
            self._file("mat/UNLISTED1" + suffix)
        self._file("mat/UNLISTED1.stamp.json", json.dumps(
            {"id": "UNLISTED1", "name": "Back", "renderer": "Karma"}))
        opened = []
        real_open = builtins.open

        def counting(path, *args, **kwargs):
            if str(path).endswith(material.STAMP_SUFFIX):
                opened.append(os.path.basename(str(path)))
            return real_open(path, *args, **kwargs)

        with patch.object(builtins, "open", counting):
            findings = self._survey()
            repair.report_lines(findings)
            repair.materials_on_record(findings)
        self.assertEqual(["UNLISTED1.stamp.json"], opened)


class TheSurveyAnswersEverythingTest(_Library):
    """One survey: files and renders gone, rows with no category, a shrunk list."""

    def _cops(self, rows):
        self._write(os.path.join(self.dir, "cops.json"),
                    {"version": 8, "categories": ["_All"], "tags": [], "assets": rows})

    def _pair(self, asset_id):
        for suffix in (".mat", ".interface"):
            self._file("mat/" + asset_id + suffix)

    def test_listed_rows_whose_files_are_gone_are_named(self):
        os.remove(os.path.join(self.mat_dir, self.first_id + ".mat"))
        findings = self._survey()
        name = self._read(self.index)["assets"][0]["name"]
        self.assertEqual([(self.first_id, name)], findings["missing_files"]["library.json"])
        text = "\n".join(repair.report_lines(findings))
        self.assertIn("1 material", text)
        self.assertIn(name, text)

    def test_a_render_is_missed_only_where_a_tile_can_hold_one(self):
        os.remove(os.path.join(self.img_dir, self.first_id + ".png"))
        self._pair("LOPSETUP1")
        self._pair("SOPSETUP1")
        self._cops([{"id": "LOPSETUP1", "name": "Stage", "renderer": "LOP", "categories": ["a"]},
                    {"id": "SOPSETUP1", "name": "Rock", "renderer": "SOP", "categories": ["a"]}])
        findings = self._survey()
        self.assertEqual([self.first_id],
                         [one for one, _name in findings["missing_renders"]["library.json"]])
        self.assertEqual(["SOPSETUP1"],
                         [one for one, _name in findings["missing_renders"]["cops.json"]])
        text = "\n".join(repair.report_lines(findings))
        self.assertIn("1 material and 1 node", text)
        self.assertNotIn("2 materials", text)

    def test_the_model_and_the_engine_read_one_renderable_set(self):
        from amaze.core import cop_library
        self.assertIs(renderers.RENDERABLE_CONTEXTS, cop_library.CopLibrary.RENDERABLE)

    def test_rows_with_no_category_are_found_and_put_in_one(self):
        document = self._read(self.index)
        document["assets"][0]["categories"] = [" "]
        self._write(self.index, document)
        findings = self._survey()
        self.assertEqual([self.first_id],
                         [one for one, _name in findings["uncategorised"]["library.json"]])
        repair.rescue_uncategorised(findings)
        after = self._read(self.index)
        self.assertEqual(["Uncategorized"], after["assets"][0]["categories"])
        self.assertIn("Uncategorized", after["categories"])
        self.assertEqual({}, {key: value for key, value
                              in self._survey()["uncategorised"].items() if value})

    def test_a_list_holding_under_half_of_its_newest_copy_is_shrunk(self):
        document = self._read(self.index)
        self._write(self.index + ".bak-1", document)
        self._write(self.index, dict(document, assets=document["assets"][:1]))
        findings = self._survey()
        self.assertEqual([("library.json", 1, len(document["assets"]))], findings["shrunk"])
        self.assertIn("newest saved copy holds %d" % len(document["assets"]),
                      "\n".join(repair.report_lines(findings)))

    def test_a_healthy_library_gets_one_line_per_question_and_the_holding_folder_last(self):
        findings = self._survey()
        for key in ("missing_files", "missing_renders", "uncategorised"):
            self.assertEqual({}, {k: v for k, v in findings[key].items() if v}, key)
        for key in ("leftovers", "held_back", "unknown", "unknown_folders", "shrunk"):
            self.assertEqual([], findings[key], key)
        lines = [line for line in repair.report_lines(findings) if line]
        self.assertIn("holding folder on this computer", lines[-1])
        self.assertIn(findings["holding"]["path"], lines[-1])
        text = "\n".join(lines)
        for said in ("Every material and node", "has a category",
                     "Nothing is left over"):
            self.assertIn(said, text)
        for word in ("index", "record", "row", "database", "orphan", "stale"):
            self.assertNotIn(word, text.lower())


class TheFilesSectionTest(_Library):
    """A folder not on this computer, and a star on a file gone from a folder that is."""

    def setUp(self):
        super().setUp()
        from amaze.core import locations
        locations.forget()
        self.addCleanup(locations.forget)
        root = test_support.scratch_dir("amaze_check_files_")
        self.addCleanup(shutil.rmtree, root, True)
        self.gone = os.path.join(root, "Gone")
        self.here = os.path.join(root, "Here")
        for folder in (self.gone, self.here):
            os.makedirs(folder)
            self.prefs.add_file_folder(folder)
        self.star = os.path.join(self.here, "rock.png")
        open(self.star, "w").close()
        self.prefs.add_file_favorite(self.star)
        self.assertIn(hostos.canonical_path_key(self.star),
                      [hostos.canonical_path_key(p) for p in self.prefs.file_favorites],
                      "premise: the star did not land")
        os.rename(self.gone, self.gone + ".elsewhere")
        os.remove(self.star)

    def _keys(self, paths):
        return [hostos.canonical_path_key(path) for path in paths]

    def test_they_are_named_and_set_aside_by_their_own_actions(self):
        findings = repair.survey(self.prefs)
        self.assertEqual(self._keys([self.gone]), self._keys(findings["dead_folders"]))
        self.assertEqual(self._keys([self.star]), self._keys(findings["dead_stars"]))
        text = "\n".join(repair.report_lines(findings))
        self.assertIn(self.gone, text)
        self.assertIn(self.star, text)
        repair.set_aside_folders(findings)
        repair.drop_dead_stars(findings)
        self.assertEqual(self._keys([self.here]), self._keys(self.prefs.file_folders))
        self.assertEqual([], self.prefs.file_favorites)

    def test_a_folder_back_since_the_check_is_kept(self):
        findings = repair.survey(self.prefs)
        os.rename(self.gone + ".elsewhere", self.gone)
        self.assertEqual([], repair.set_aside_folders(findings))
        self.assertIn(hostos.canonical_path_key(self.gone), self._keys(self.prefs.file_folders))


class AnActionRefusesAHeldLibraryUnlessThePanelSaysItLetGoTest(_Library):

    def test_every_action_takes_a_guard(self):
        import inspect
        for name in ("add_materials_back", "reattach", "put_back", "repair_index",
                     "move_aside", "set_aside_folders", "drop_dead_stars",
                     "rescue_uncategorised"):
            parameters = inspect.signature(getattr(repair, name)).parameters
            self.assertIn("guard", parameters, name)
            self.assertIs(True, parameters["guard"].default, name)

    def test_the_guard_refuses_and_guard_false_acts(self):
        self._file("mat/%s.mat.pre-adopt" % self.first_id)
        findings = self._survey()
        with patch.object(repair, "session_has_a_library_open", return_value=True):
            with self.assertRaises(ValueError):
                repair.move_aside(findings, "leftovers")
            result = repair.move_aside(findings, "leftovers", guard=False)
        self.assertEqual(1, len(result["moved"]))


class RepairIndexTest(_Library):

    def test_a_full_older_copy_is_taken_over_an_empty_newer_one(self):
        document = self._read(self.index)
        self._write(self.index + ".bak-1", dict(document, assets=[]))
        self._write(self.index + ".bak-2", document)
        with open(self.index, "w", encoding="utf-8") as handle:
            handle.write('{"assets": [')
        ok, how = repair.repair_index(self.dir, "mat/")
        self.assertTrue(ok, how)
        self.assertEqual(len(document["assets"]), len(self._read(self.index)["assets"]),
                         "an empty copy was put back while a full one sat beside it")

    def test_an_empty_copy_is_taken_when_no_copy_holds_anything(self):
        document = self._read(self.index)
        self._write(self.index + ".bak-1", dict(document, assets=[]))
        with open(self.index, "w", encoding="utf-8") as handle:
            handle.write('{"assets": [')
        ok, how = repair.repair_index(self.dir, "mat/")
        self.assertTrue(ok, how)
        self.assertEqual([], self._read(self.index)["assets"][:0])


class TheHoldingFolderTest(_Library):
    """It expires on every survey and every move, and follows the library by its id."""

    def _old_day(self):
        day = time.strftime("%Y-%m-%d", time.localtime(time.time() - 40 * 86400))
        folder = os.path.join(os.path.dirname(quarantine.quarantine_folder(self.dir)), day)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "held.mat"), "w") as handle:
            handle.write("x")
        return folder

    def test_every_survey_expires_it(self):
        old = self._old_day()
        findings = self._survey()
        self.assertFalse(os.path.exists(old), "a day past the window survived a check")
        self.assertEqual(0, findings["holding"]["files"])

    def test_every_move_aside_expires_it(self):
        findings = self._survey()
        old = self._old_day()
        repair.move_aside(findings, "leftovers")
        self.assertFalse(os.path.exists(old))

    def test_the_survey_says_what_it_holds_and_when_each_day_goes(self):
        self._file("mat/%s.mat.pre-adopt" % self.first_id, "abcd")
        repair.move_aside(self._survey(), "leftovers")
        holding = self._survey()["holding"]
        self.assertEqual((1, 4), (holding["files"], holding["bytes"]))
        today = time.strftime("%Y-%m-%d")
        self.assertEqual(today, holding["days"][0][0])
        expires = time.strftime("%Y-%m-%d", time.localtime(time.time() + 31 * 86400))
        self.assertEqual(expires, holding["days"][0][1])

    def test_the_library_id_is_minted_once(self):
        first = library_policy.library_id(self.dir)
        self.assertRegex(first, r"^[0-9a-f]{32}$")
        self.assertEqual(first, library_policy.library_id(self.dir))
        with open(os.path.join(self.dir, "policy.json"), encoding="utf-8") as handle:
            self.assertEqual(first, json.load(handle)["library_id"])

    def test_an_unreadable_policy_is_not_written_over_for_an_id(self):
        path = self._file("policy.json", "{ broken")
        self.assertEqual("", library_policy.library_id(self.dir))
        with open(path, encoding="utf-8") as handle:
            self.assertEqual("{ broken", handle.read())

    def test_the_holding_folder_and_history_follow_the_library_id(self):
        by_path = hostos.history_root(self.index)
        held = os.path.join(by_path, quarantine.QUARANTINE_PREFIX, "2026-11-01")
        os.makedirs(held)
        with open(os.path.join(held, "kept.mat"), "w") as handle:
            handle.write("kept")
        library_id = library_policy.library_id(self.dir)
        by_id = hostos.history_root(self.index)
        self.assertIn(library_id, by_id)
        self.assertNotEqual(by_path, by_id)
        self.assertFalse(os.path.exists(by_path), "the folder keyed by the path stayed behind")
        self.assertTrue(os.path.exists(os.path.join(
            by_id, quarantine.QUARANTINE_PREFIX, "2026-11-01", "kept.mat")),
            "what the holding folder held did not come with it")
        self.assertTrue(quarantine.quarantine_folder(self.dir).startswith(by_id))
        moved = os.path.join(os.path.dirname(os.path.dirname(self.dir.rstrip("/\\"))),
                             "moved_library")
        shutil.copytree(self.dir, moved)
        self.addCleanup(shutil.rmtree, moved, True)
        self.assertEqual(by_id, hostos.history_root(os.path.join(moved, "library.json")),
                         "a moved library lost its history and holding folder")

    def test_opening_the_library_mints_its_id(self):
        from amaze.actions import library as library_actions
        with patch.object(library_actions.locations, "ready", return_value=True):
            library_actions.update(self.prefs)
        with open(os.path.join(self.dir, "policy.json"), encoding="utf-8") as handle:
            self.assertRegex(json.load(handle).get("library_id", ""), r"^[0-9a-f]{32}$")


class PutBackTest(_Library):
    """A put-back through any door adds back the materials saved after the copy."""

    def test_the_shelf_s_put_back_adds_the_materials_saved_after_the_copy(self):
        document = self._read(self.index)
        self._write(self.index + ".bak-1", document)
        for suffix in (".mat", ".interface"):
            self._file("mat/NEWER001" + suffix)
        self._file("mat/NEWER001.stamp.json", json.dumps(
            {"id": "NEWER001", "name": "Saved Later", "renderer": "Karma",
             "categories": ["Later"]}))
        with open(self.index, "w", encoding="utf-8") as handle:
            handle.write("{ broken")
        done = repair.put_back(self._survey(), "library.json", "bak-1")
        ids = [str(row["id"]) for row in self._read(self.index)["assets"]]
        self.assertIn("NEWER001", ids)
        self.assertIn("added back", done["said"])


class TheShrinkIsSaidAtLoadTest(_Library):

    def test_a_shrunk_list_alerts_when_it_loads(self):
        self.addCleanup(database.DatabaseConnector._integrity_notes.clear)    # Clean Up's queue
        document = self._read(self.index)
        self._write(self.index + ".bak-1", document)
        self._write(self.index, dict(document, assets=document["assets"][:1]))
        said = []
        with patch.object(debug, "alert", side_effect=lambda message, **_: said.append(message)):
            database.DatabaseConnector("library.json").load(self.dir)
        self.assertEqual(1, len(said), "a list holding under half of its newest copy opened in silence")
        self.assertIn("%d" % len(document["assets"]), said[0])


class TheAuditToolTest(unittest.TestCase):
    """It reads the convention from its one home and runs with no Houdini at all."""

    def _run(self, library):
        return subprocess.run([test_support.plain_python(), "-I", AUDIT, "--strict", library],
                              capture_output=True, text=True, timeout=60)

    def test_a_clean_library_passes(self):
        done = self._run(test_support.fresh_library(self))
        self.assertEqual(0, done.returncode, done.stdout + done.stderr)

    def test_one_of_each_kind_fails_and_is_named(self):
        library = test_support.fresh_library(self)
        for relative in ("mat/a.mat.x1.writing", "mat/a.mat.pre-adopt",
                         "notes.json 2.bak-3", "stray.txt", "matX/pack/half.tmp"):
            path = os.path.join(library, *relative.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w").close()
        os.makedirs(os.path.join(library, "img", "comments"))
        done = self._run(library)
        self.assertEqual(1, done.returncode, done.stdout + done.stderr)
        for kind, relative in (("scratch", "mat/a.mat.x1.writing"),
                               ("pre-adopt", "mat/a.mat.pre-adopt"),
                               ("duplicate", "notes.json 2.bak-3"),
                               ("unknown", "stray.txt"),
                               ("scratch", "matX/pack/half.tmp"),
                               ("unknown", "img/comments/")):
            line = next((one for one in done.stdout.splitlines() if relative in one), "")
            self.assertIn(kind, line, "%s is not named as %s:\n%s" % (relative, kind, done.stdout))


if __name__ == "__main__":
    unittest.main(verbosity=2)
