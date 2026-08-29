"""Repair: the way out of Clean Library's refusal, and the route to it."""

import ast
import datetime
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, patch

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets                             # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou                                                # noqa: E402

from amaze.core import category, database, repair         # noqa: E402
from amaze.core import library as library_mod             # noqa: E402
from amaze.core import multifilterproxy_model             # noqa: E402
from amaze.helpers import hostos                          # noqa: E402
from amaze.helpers import restore as restore_lib          # noqa: E402
from amaze.tests import test_support                      # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
SHELF = os.path.join(REPO, "toolbar", "Amaze.shelf")


class _Case(unittest.TestCase):
    """A private copy of the fixture library and a clean registry."""

    COP_ID = "COPOWNED1"

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.dir = self.prefs.dir
        self.mat_dir = os.path.join(self.dir, self.prefs.asset_dir)
        self.img_dir = os.path.join(self.dir, self.prefs.img_dir)
        self.cops = os.path.join(self.dir, "cops.json")

    def _survey(self):
        return repair.survey(self.dir, self.prefs.asset_dir,
                             self.prefs.img_dir)

    def _pair(self, asset_id=None):
        """The two files an asset owns, listed by nothing."""
        asset_id = asset_id or self.COP_ID
        paths = []
        for suffix in (".mat", ".interface"):
            path = os.path.join(self.mat_dir, asset_id + suffix)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("owned by " + asset_id + "\n")
            paths.append(path)
        return paths

    def _write(self, path, document):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=4)

    def _cops(self, assets):
        self._write(self.cops, {"version": 2, "categories": ["_All"],
                                "tags": [], "assets": assets})

    def _read(self, path):
        with open(path, encoding="utf-8-sig") as handle:
            return json.load(handle)


class TheReportSaysWhatIsWrongTest(_Case):
    """A report nobody can act on is a log with a dialog around it."""

    def test_a_healthy_library_says_so_and_offers_nothing_to_fix(self):
        findings = self._survey()
        self.assertTrue(findings["complete"])
        self.assertEqual(0, repair.unaccounted_total(findings))
        text = "\n".join(repair.report_lines(findings))
        self.assertIn("the list reads fine", text)
        self.assertIn("Every file in the library's own folders is "
                      "accounted for", text)
        choices, actions = repair._choices(findings, may_change=True)
        self.assertEqual(["Close"], choices,
                         "Repair offered an action on a library with "
                         "nothing wrong - a button that changes nothing is "
                         "an invitation to break something")

    def test_an_empty_list_and_its_files_are_both_named(self):
        self._cops([])
        self._pair()
        findings = self._survey()
        text = "\n".join(repair.report_lines(findings))
        self.assertIn("Node: the list is there and holds nothing.", text)
        self.assertIn("2 files in the mat folder", text,
                      "the report does not say how many files, in which "
                      "folder - a combined total cannot be checked against "
                      "the refusal that sent the reader here, which counts "
                      "the asset folder alone")
        self.assertIn("COPOWNED1.mat", text,
                      "the files are counted but not named, and the next "
                      "dialog offers to move them")

    def test_two_empty_lists_get_one_explanation_between_them(self):
        """One line for the ambiguity, no less than the refusal said, and not twice."""
        self._cops([])
        with open(os.path.join(self.dir, "code.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"version": 2, "categories": ["_All"], "tags": [],
                       "assets": []}, handle)
        lines = repair.report_lines(self._survey())
        explanations = [line for line in lines
                        if "looks the same whether" in line]
        self.assertEqual(1, len(explanations),
                         "one dialog carried the same explanation twice")
        self.assertIn("nothing was ever saved there", explanations[0])
        self.assertIn("failed to load", explanations[0])

    def test_an_unreadable_list_is_named_and_stops_any_moving(self):
        """While a list cannot be read, no file may be called unclaimed."""
        with open(self.cops, "w", encoding="utf-8") as handle:
            handle.write('{"assets": [{"id": "COPOWNED1"}')     # truncated
        self._pair()
        findings = self._survey()
        self.assertFalse(findings["complete"])
        text = "\n".join(repair.report_lines(findings))
        self.assertIn("Node: the list is there and Amaze cannot read it.",
                      text)
        self.assertIn("Amaze could not check the Node list either, so "
                      "some of those files may be its", text,
                      "the report points at 'a list above' instead of "
                      "naming the section whose files may be at risk")
        choices, actions = repair._choices(findings, may_change=True)
        self.assertNotIn("quarantine", actions,
                         "moving files aside was offered while a list "
                         "could not be read - the files may be its")
        self.assertNotIn("reattach", actions,
                         "adding files to a list was offered while another "
                         "list could not be read")
        with self.assertRaises(ValueError):
            repair.quarantine(findings)

    def test_a_list_that_has_not_arrived_is_told_apart_from_a_new_one(self):
        """Absent is new only when nothing says the file was ever here."""
        blank = self._survey()
        nodes = [e for e in blank["lists"] if e["filename"] == "cops.json"][0]
        self.assertEqual("absent", nodes["state"])
        self.assertIn("Node: nothing saved here yet.",
                      "\n".join(repair.report_lines(blank)))

        self._write(self.cops + ".bak-1", {"assets": [{"id": self.COP_ID}]})
        findings = self._survey()
        nodes = [e for e in findings["lists"]
                 if e["filename"] == "cops.json"][0]
        self.assertEqual("absent-but-known", nodes["state"])
        self.assertFalse(findings["complete"])
        text = "\n".join(repair.report_lines(findings))
        self.assertIn("Amaze can see there was one here before", text,
                      "the report does not say the list was here before")
        self.assertIn("still be on its way", text)
        self.assertIn("run Repair again", text,
                      "a list that may still be arriving is reported with "
                      "no next step")
        self.assertNotIn("cops.json.bak-1", text,
                         "the report names a file the reader has never "
                         "opened in a sentence that does not send them to "
                         "it")

    def test_the_saved_copies_say_what_each_would_bring_back(self):
        """The count and the date are the answer; a filename is not."""
        self._cops([])
        self._write(self.cops + ".bak-1",
                    {"assets": [{"id": "A"}, {"id": "B"}]})
        self._write(self.cops + ".bak-first", {"assets": [{"id": "A"}]})
        findings = self._survey()
        text = "\n".join(repair.report_lines(findings))
        self.assertRegex(text, r"from \d{4}-\d{2}-\d{2} \d\d:\d\d, "
                               r"2 saved nodes")
        self.assertRegex(text, r"from \d{4}-\d{2}-\d{2} \d\d:\d\d, "
                               r"1 saved node",
                         "the count arrives without the word for what was "
                         "counted, or without agreeing with it")
        for suffix in ("bak-1", "bak-first"):
            self.assertNotIn(suffix, text,
                             "the report asks the reader to choose by "
                             "'%s', which nothing in Houdini has ever "
                             "shown them" % suffix)

    def test_a_copy_that_cannot_be_read_is_not_offered_as_a_rescue(self):
        """A backup can be truncated too, so a listed copy must be readable."""
        self._cops([])
        with open(self.cops + ".bak-1", "w", encoding="utf-8") as handle:
            handle.write("{ truncated")
        findings = self._survey()
        text = "\n".join(repair.report_lines(findings))
        self.assertRegex(text, r"from \d{4}-\d{2}-\d{2} \d\d:\d\d, "
                               r"cannot be read")

    def test_a_colors_file_of_the_wrong_shape_is_not_called_empty(self):
        """A file nothing can be counted in reads as unreadable, never empty."""
        with open(os.path.join(self.dir, "gradients.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(["not", "a", "list", "Amaze", "wrote"], handle)
        findings = self._survey()
        colors = [e for e in findings["lists"]
                  if e["filename"] == "gradients.json"][0]
        self.assertEqual("unreadable", colors["state"])
        self.assertFalse(findings["complete"],
                         "a list nobody can read left the union looking "
                         "complete, so files could be moved on a guess")

    def test_a_broken_colors_file_that_still_COUNTS_is_unreadable(self):
        """The shape `count_in` answers 1 for, which the connector refuses."""
        with open(os.path.join(self.dir, "gradients.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"version": 3, "categories": ["_All"],
                       "tags": [], "assets": "oops"}, handle)
        findings = self._survey()
        colors = [e for e in findings["lists"]
                  if e["filename"] == "gradients.json"][0]
        self.assertEqual(
            "unreadable", colors["state"],
            "Repair called a broken Colors list healthy - the tool whose "
            "whole job is saying what is wrong said nothing was")
        self.assertFalse(
            findings["complete"],
            "the union looked complete over a list nobody can read, so "
            "files could be moved aside on a guess")

    def test_a_healthy_colors_file_is_still_ok(self):
        """The accept path: a healthy Colors library must not read as broken."""
        findings = self._survey()
        colors = [e for e in findings["lists"]
                  if e["filename"] == "gradients.json"][0]
        self.assertIn(colors["state"], ("ok", "empty", "absent"),
                      "a healthy Colors list was called %s"
                      % colors["state"])

    def test_a_folder_it_could_not_read_is_not_called_accounted_for(self):
        """A neutral value makes a failure indistinguishable from an empty result."""
        shutil.rmtree(self.mat_dir)
        findings = self._survey()
        self.assertEqual([self.prefs.asset_dir],
                         findings["unreadable_folders"])
        self.assertFalse(
            findings["complete"],
            "a folder Amaze could not look inside left the union looking "
            "complete, so files could have been moved on a guess")
        text = "\n".join(repair.report_lines(findings))
        self.assertIn("could not look inside the mat folder", text)
        self.assertNotIn("is accounted for by a section", text,
                         "Repair reported a folder it could not read as "
                         "accounted for")
        choices, actions = repair._choices(findings, may_change=True)
        self.assertEqual(["Close"], choices,
                         "an action was offered while a whole folder was "
                         "unread")
        with self.assertRaises(ValueError):
            repair.quarantine(findings)

    def test_the_two_buttons_say_how_many_files_each_one_acts_on(self):
        """Two buttons act on two different sets, so each says its own count."""
        self._cops([])
        self._pair()
        with open(os.path.join(self.mat_dir, "HALFONLY2.mat"), "w",
                  encoding="utf-8") as handle:
            handle.write("no .interface beside me\n")
        findings = self._survey()
        self.assertEqual(3, repair.unaccounted_total(findings),
                         "premise: one of the three files must be half a "
                         "pair")
        choices, actions = repair._choices(findings, may_change=True)
        self.assertIn("Add 2 Files to a Section", choices)
        self.assertIn("Move 3 Files Aside", choices)
        text = "\n".join(repair.report_lines(findings))
        self.assertIn("Of those, 2 files can be added back", text,
                      "nothing tells the reader the two buttons cover "
                      "different files")

    def test_the_report_avoids_the_words_the_style_guide_bans(self):
        """The user's words: these exist only because of how it was built."""
        self._cops([])
        self._pair()
        with open(os.path.join(self.dir, "code.json"), "w",
                  encoding="utf-8") as handle:
            handle.write("{ truncated")
        text = " ".join(repair.report_lines(self._survey())).lower()
        for word in ("index", "record", "row", "database", "session",
                     "merge", "schema", "orphan", "stale", "connector",
                     "atomic", "manifest"):
            self.assertNotIn(word, text,
                             "the report uses '%s', which is a word about "
                             "how Amaze is built, not about the library"
                             % word)


class RepairNeverDeletesTest(unittest.TestCase):
    """The one property that may not regress, read from source with `ast`."""

    FORBIDDEN = {
        ("os", "remove"), ("os", "unlink"), ("os", "rmdir"),
        ("os", "removedirs"), ("shutil", "rmtree"), ("shutil", "move"),
        ("pathlib", "unlink"),
    }

    def test_the_module_contains_no_delete_call_at_all(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "core", "repair.py")
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        found = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value,
                                                              ast.Name):
                if (func.value.id, func.attr) in self.FORBIDDEN:
                    found.append("%s.%s line %d"
                                 % (func.value.id, func.attr, node.lineno))
            if isinstance(func, ast.Name) and func.id in ("unlink",
                                                          "rmtree"):
                found.append("%s line %d" % (func.id, node.lineno))
        self.assertEqual(
            [], found,
            "repair.py calls %s - Repair may only ever MOVE a file, and if "
            "a delete is needed here the design is wrong" % ", ".join(found))

    def test_the_test_can_fail(self):
        """The walk has to be able to find one, or it is checking nothing."""
        tree = ast.parse("import os\nos.remove('x')\n")
        hits = [n for n in ast.walk(tree)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and (getattr(n.func.value, "id", ""), n.func.attr)
                in self.FORBIDDEN]
        self.assertEqual(1, len(hits))


class MovingFilesAsideTest(_Case):
    """Quarantine: the strongest thing Repair may do."""

    def test_files_are_moved_not_deleted_and_keep_their_bytes(self):
        self._cops([])
        paths = self._pair()
        before = {os.path.basename(p): open(p, "rb").read() for p in paths}
        findings = self._survey()
        result = repair.quarantine(findings)
        for path in paths:
            self.assertFalse(os.path.exists(path),
                             "%s was left where it was" % path)
        moved_dir = os.path.join(result["folder"],
                                 self.prefs.asset_dir.rstrip("/\\"))
        for name, content in before.items():
            landed = os.path.join(moved_dir, name)
            self.assertTrue(os.path.exists(landed),
                            "%s did not arrive in the folder aside" % name)
            with open(landed, "rb") as handle:
                self.assertEqual(content, handle.read(),
                                 "%s changed on the way" % name)
        self.assertEqual(sorted(before), sorted(result["moved"]))
        self.assertEqual([], result["failed"])

    def test_the_folder_is_THE_quarantine_not_a_second_one(self):
        """One quarantine for both tools, machine-local, with the 30-day window."""
        from amaze.core import library as library_mod
        self._cops([])
        self._pair()
        result = repair.quarantine(self._survey())
        self.assertEqual(
            os.path.normpath(library_mod.quarantine_folder(self.dir)),
            os.path.normpath(result["folder"]),
            "Repair quarantines somewhere other than Clean Library")
        self.assertFalse(
            os.path.normpath(result["folder"]).startswith(
                os.path.normpath(self.dir)),
            "the quarantine is inside the synced library again")

    def test_a_second_round_the_same_day_keeps_the_first_copy(self):
        """`os.replace` overwrites, and the holding folder is named per day."""
        self._cops([])
        path = os.path.join(self.mat_dir, self.COP_ID + ".mat")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("ROUND ONE BYTES\n")
        first = repair.quarantine(self._survey())
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("ROUND TWO BYTES\n")
        second = repair.quarantine(self._survey())
        self.assertEqual(first["folder"], second["folder"],
                         "premise: both rounds must land in the same dated "
                         "folder, or the collision cannot happen")
        landed = []
        for root, _dirs, names in os.walk(first["folder"]):
            for name in names:
                with open(os.path.join(root, name), encoding="utf-8") as fh:
                    landed.append(fh.read())
        self.assertIn("ROUND ONE BYTES\n", landed,
                      "the first copy's bytes were overwritten by the "
                      "second round - a delete wearing a move's name")
        self.assertIn("ROUND TWO BYTES\n", landed)

    def test_the_quarantine_folder_is_invisible_to_the_next_sweep(self):
        """A top-level folder is in neither list the next sweep walks."""
        self._cops([])
        self._pair()
        result = repair.quarantine(self._survey())
        again = self._survey()
        self.assertEqual(0, repair.unaccounted_total(again),
                         "the files aside are still counted as unclaimed, "
                         "so Repair would offer to move them again forever")
        self.assertTrue(os.path.isdir(result["folder"]),
                        "premise: the folder aside must still be there")


class AddingUnlistedFilesBackTest(_Case):
    """Re-attach: the last resort when no saved copy holds the rows."""

    def test_a_pair_comes_back_as_something_the_app_can_read(self):
        from amaze.core import material as material_mod

        self._cops([])
        self._pair()
        findings = self._survey()
        result = repair.reattach(findings, "library.json")
        self.assertEqual([self.COP_ID], result["added"])
        document = self._read(os.path.join(self.dir, "library.json"))
        rows = [r for r in document["assets"] if r.get("id") == self.COP_ID]
        self.assertEqual(1, len(rows), "the asset was not added once")
        # Through the real loader: the row shape has to be the app's own.
        asset = material_mod.Material.from_dict(rows[0])
        self.assertEqual(self.COP_ID, str(asset.mat_id))
        self.assertIn(repair.RECOVERED_CATEGORY, document["categories"])
        self.assertEqual(
            [], [name for name in os.listdir(self.dir)
                 if ".repairing" in name],
            "a scratch file was left in the library folder - an unowned "
            "file there is exactly what the next sweep has to puzzle over")
        self.assertEqual(0, repair.unaccounted_total(self._survey()),
                         "the files are still unclaimed after being added "
                         "back, so Clean Library would still refuse")

    def test_the_stamp_beside_the_files_names_the_asset(self):
        """▸p/recovery-stamp: Repair is the sanctioned reader, and this is a repair."""
        import json as json_mod

        self._cops([])
        self._pair()
        with open(os.path.join(self.mat_dir,
                               self.COP_ID + ".stamp.json"), "w",
                  encoding="utf-8") as handle:
            json_mod.dump({"id": self.COP_ID, "name": "Brushed Copper",
                           "categories": ["Metals"], "tags": ["copper", "pbr"],
                           "description": "the one from the kitchen shot",
                           "renderer": "Karma"}, handle)

        repair.reattach(self._survey(), "library.json")

        document = self._read(os.path.join(self.dir, "library.json"))
        row = [r for r in document["assets"]
               if r.get("id") == self.COP_ID][0]
        self.assertEqual(
            "Brushed Copper", row.get("name"),
            "the name sat in the stamp beside the files and Repair minted a "
            "placeholder instead; the next save then rewrites that stamp")
        self.assertEqual(["Metals"], row.get("categories"))
        self.assertIn("Metals", document["categories"])
        self.assertEqual(["copper", "pbr"], row.get("tags"))

    def test_a_pair_with_no_stamp_still_comes_back_named(self):
        """The fallback: no stamp, or one that will not parse, still reattaches."""
        self._cops([])
        self._pair()
        with open(os.path.join(self.mat_dir,
                               self.COP_ID + ".stamp.json"), "w",
                  encoding="utf-8") as handle:
            handle.write("{not json")

        result = repair.reattach(self._survey(), "library.json")

        self.assertEqual([self.COP_ID], result["added"])
        document = self._read(os.path.join(self.dir, "library.json"))
        row = [r for r in document["assets"]
               if r.get("id") == self.COP_ID][0]
        self.assertTrue(str(row.get("name", "")).startswith("Recovered "),
                        "an unreadable stamp must fall back, not raise")
        self.assertIn(repair.RECOVERED_CATEGORY, document["categories"])

    def test_only_a_complete_pair_is_offered(self):
        """Half a pair would put a tile in the panel that cannot open."""
        self._cops([])
        with open(os.path.join(self.mat_dir, "HALFONLY1.mat"), "w",
                  encoding="utf-8") as handle:
            handle.write("no .interface beside me\n")
        findings = self._survey()
        self.assertEqual([], repair._complete_pairs(findings))
        self.assertEqual(1, repair.unaccounted_total(findings),
                         "premise: the half file must still be reported")
        choices, actions = repair._choices(findings, may_change=True)
        self.assertNotIn("reattach", actions)

    def test_a_COP_companion_is_not_the_material_half_of_a_pair(self):
        """`X_cop.mat` must not count as X's `.mat`, or Add Back mints a dead row."""
        self._cops([])
        for name, body in (("PAIRCOP1_cop.mat", "the companion\n"),
                           ("PAIRCOP1.interface", "the interface\n")):
            with open(os.path.join(self.mat_dir, name), "w",
                      encoding="utf-8") as handle:
                handle.write(body)

        findings = self._survey()
        self.assertEqual(
            [], repair._complete_pairs(findings),
            "a COP companion was counted as the material half, so Add "
            "Back would write a row with no .mat behind it")
        choices, actions = repair._choices(findings, may_change=True)
        self.assertNotIn("reattach", actions)

    def test_a_real_pair_beside_a_companion_is_still_offered(self):
        """The accept path: a genuine pair beside a companion still comes back."""
        self._cops([])
        for name in ("PAIRFULL1.mat", "PAIRFULL1.interface",
                     "PAIRFULL1_cop.mat"):
            with open(os.path.join(self.mat_dir, name), "w",
                      encoding="utf-8") as handle:
                handle.write("owned by PAIRFULL1\n")
        self.assertEqual(["PAIRFULL1"],
                         repair._complete_pairs(self._survey()))

    def test_it_refuses_while_a_list_cannot_be_read(self):
        self._cops([])
        self._pair()
        with open(os.path.join(self.dir, "code.json"), "w",
                  encoding="utf-8") as handle:
            handle.write("{ truncated")
        with self.assertRaises(ValueError):
            repair.reattach(self._survey(), "library.json")

    def test_the_list_it_writes_is_still_loadable_by_the_app(self):
        """Written through `Material.get_as_dict`; a hand-built row drifts."""
        self._cops([])
        self._pair()
        repair.reattach(self._survey(), "cops.json")
        from amaze.core import cop_library
        model = cop_library.CopLibrary(preferences=self.prefs)
        self.assertIn(self.COP_ID, [str(a.mat_id) for a in model.assets],
                      "the Nodes section cannot see what Repair added")


class PuttingASavedCopyBackTest(_Case):
    """One restore, shared with the terminal tool."""

    def test_the_copy_lands_and_the_current_state_is_kept(self):
        self._cops([])
        self._write(self.cops + ".bak-1",
                    {"version": 2, "categories": ["_All"], "tags": [],
                     "assets": [{"id": "A"}, {"id": "B"}]})
        done = repair.put_back(self._survey(), "cops.json", "bak-1")
        self.assertEqual(2, len(self._read(self.cops)["assets"]))
        # The undo copy is timestamped, never a fixed name.
        self.assertTrue(
            done["undo"].startswith("cops.json.bak-before-restore-"),
            "the undo copy is not named per restore: %r" % done["undo"])
        self.assertEqual(
            [], self._read(os.path.join(self.dir, done["undo"]))["assets"],
            "the list that was there is not in the undo copy, so the "
            "restore cannot be undone")

    def test_the_undo_copy_is_offered_back_and_survives_being_used(self):
        """The promised undo has to be a copy `snapshots` will offer back."""
        self._cops([{"id": "LIVE1"}, {"id": "LIVE2"}])
        self._write(self.cops + ".bak-1",
                    {"version": 2, "categories": ["_All"], "tags": [],
                     "assets": [{"id": "OLD1"}]})
        done = repair.put_back(self._survey(), "cops.json", "bak-1")
        self.assertEqual(["OLD1"],
                         [r["id"] for r in self._read(self.cops)["assets"]])

        offered = [tier for filename, tier, _snap, _now
                   in repair.restorable(self._survey())
                   if filename == "cops.json"]
        undo_tier = done["undo"][len("cops.json."):]
        self.assertIn(undo_tier, offered,
                      "the copy the done-dialog promises is not among the "
                      "copies Repair offers, so the only route to the "
                      "promised undo is the one the tool does not have")

        repair.put_back(self._survey(), "cops.json", undo_tier)
        self.assertEqual(
            ["LIVE1", "LIVE2"],
            [r["id"] for r in self._read(self.cops)["assets"]],
            "putting the undo copy back did not bring the list you had "
            "back - the undo is a preserved copy, not a restorable one")
        self.assertEqual(
            ["LIVE1", "LIVE2"],
            [r["id"] for r in self._read(
                os.path.join(self.dir, done["undo"]))["assets"]],
            "the undo copy was consumed by being restored, so the same "
            "choice cannot flip back")

    def test_two_restores_in_a_row_keep_the_starting_state(self):
        """Every restore writes its own undo copy, so the trail stays walkable."""
        self._cops([{"id": "START1"}, {"id": "START2"}, {"id": "START3"}])
        self._write(self.cops + ".bak-1", {"assets": [{"id": "A"}]})
        self._write(self.cops + ".bak-2", {"assets": [{"id": "B"}]})
        first = repair.put_back(self._survey(), "cops.json", "bak-1")
        second = repair.put_back(self._survey(), "cops.json", "bak-2")
        self.assertNotEqual(first["undo"], second["undo"],
                            "two restores shared one undo name, so the "
                            "second deleted the first's copy")
        self.assertEqual(
            ["START1", "START2", "START3"],
            [r["id"] for r in self._read(
                os.path.join(self.dir, first["undo"]))["assets"]],
            "the pre-first-restore state is gone from the folder")
        offered = [tier for filename, tier, _snap, _now
                   in repair.restorable(self._survey())
                   if filename == "cops.json"]
        self.assertIn(first["undo"][len("cops.json."):], offered)
        self.assertIn(second["undo"][len("cops.json."):], offered)
        repair.put_back(self._survey(), "cops.json",
                        first["undo"][len("cops.json."):])
        self.assertEqual(
            ["START1", "START2", "START3"],
            [r["id"] for r in self._read(self.cops)["assets"]],
            "walking back to the starting state through the undo copies "
            "does not arrive at the starting state")

    def test_a_missing_copy_is_refused_without_a_tier_or_a_filename(self):
        """No storage suffix and no filename in a dialog the user reads."""
        self._cops([{"id": "LIVE1"}])
        with self.assertRaises(restore_lib.RestoreRefused) as caught:
            repair.put_back(self._survey(), "cops.json", "bak-3")
        sentence = str(caught.exception)
        self.assertNotIn("bak-3", sentence)
        self.assertNotIn("cops.json", sentence)
        self.assertIn("untouched", sentence,
                      "the refusal does not say the list you have now is "
                      "unharmed")
        self.assertIn("bak-3", caught.exception.detail,
                      "the terminal tool loses the detail it prints")

    def test_it_goes_through_the_one_shared_implementation(self):
        """A second implementation of a restore would be a second answer."""
        self._cops([])
        self._write(self.cops + ".bak-1", {"assets": [{"id": "A"}]})
        with patch.object(restore_lib, "put_back",
                          wraps=restore_lib.put_back) as spy:
            repair.put_back(self._survey(), "cops.json", "bak-1")
        self.assertEqual(1, spy.call_count,
                         "Repair restored without going through "
                         "helpers/restore.py")

    def test_a_refusal_carries_no_exception_text_for_the_dialog(self):
        """No raw exception text on screen; the detail rides in `.detail`."""
        self._cops([{"id": "LIVE1"}])
        with open(self.cops + ".bak-1", "w", encoding="utf-8") as handle:
            handle.write("{ truncated")
        with self.assertRaises(restore_lib.RestoreRefused) as caught:
            repair.put_back(self._survey(), "cops.json", "bak-1")
        sentence = str(caught.exception)
        for jargon in ("line 1", "column", "char ", "Expecting",
                       "Errno", "Traceback"):
            self.assertNotIn(jargon, sentence,
                             "the refusal a dialog would show carries '%s'"
                             % jargon)
        self.assertTrue(sentence.endswith("."),
                        "the refusal is not a finished sentence")
        self.assertIn("Expecting", caught.exception.detail,
                      "the technical half was dropped instead of moved, so "
                      "the log and the terminal lose it")

    def test_an_unreadable_copy_is_refused_not_put_back(self):
        self._cops([{"id": "LIVE1"}])
        with open(self.cops + ".bak-1", "w", encoding="utf-8") as handle:
            handle.write("{ truncated")
        with self.assertRaises(restore_lib.RestoreRefused):
            repair.put_back(self._survey(), "cops.json", "bak-1")
        self.assertEqual(1, len(self._read(self.cops)["assets"]),
                         "the live list was overwritten with something "
                         "that does not parse")

    def test_the_terminal_tool_and_the_shelf_tool_read_the_same_copies(self):
        self._cops([])
        for tier in ("bak-1", "bak-3"):
            self._write("%s.%s" % (self.cops, tier), {"assets": []})
        findings = self._survey()
        mine = [(f, t) for f, t, _snap, _now in repair.restorable(findings)
                if f == "cops.json"]
        theirs = [("cops.json", tier)
                  for tier, _path in restore_lib.snapshots(self.cops)]
        self.assertEqual(theirs, mine)


class TheGuardsTest(_Case):
    """Repair reports always; it changes only from a session with no library open."""

    def test_a_session_that_has_read_a_library_may_not_change_anything(self):
        """A connector holds its document until the process ends and saves it back."""
        self.assertFalse(repair.session_has_a_library_open(),
                         "premise: the registry starts empty")
        connector = database.DatabaseConnector("cops.json")
        self.assertTrue(repair.session_has_a_library_open())
        self.assertIsNotNone(connector)

    def test_the_actions_themselves_refuse_such_a_session(self):
        """The guard belongs to the operations; a withheld button protects one caller."""
        self._cops([])
        paths = self._pair()
        self._write(self.cops + ".bak-1", {"assets": [{"id": "A"}]})
        findings = self._survey()
        database.DatabaseConnector("cops.json")     # the panel, earlier
        self.assertTrue(repair.session_has_a_library_open(), "premise")
        with self.assertRaises(restore_lib.RestoreRefused) as caught:
            repair.put_back(findings, "cops.json", "bak-1")
        self.assertIn("quit Houdini", str(caught.exception),
                      "the refusal does not say the step that works")
        with self.assertRaises(ValueError):
            repair.quarantine(findings)
        with self.assertRaises(ValueError):
            repair.reattach(findings, "cops.json")
        self.assertEqual([], self._read(self.cops)["assets"],
                         "a list was changed by an action that should "
                         "have refused this Houdini")
        for path in paths:
            self.assertTrue(os.path.exists(path),
                            "a file was moved by a refused action")

    def test_no_action_is_offered_to_such_a_session(self):
        self._cops([])
        self._pair()
        self._write(self.cops + ".bak-1", {"assets": [{"id": "A"}]})
        findings = self._survey()
        offered, actions = repair._choices(findings, may_change=True)
        self.assertIn("restore", actions,
                      "premise: this library must have something to offer")
        held, actions = repair._choices(findings, may_change=False)
        self.assertEqual(["Close"], held,
                         "a button was offered that would be written over "
                         "from memory the moment Amaze next saves")

    def test_finding_no_panel_does_not_raise_without_a_desktop(self):
        """It must work with no interface at all, which is how the suite runs."""
        self.assertIsNone(repair.open_panel_tab())

    def test_no_library_folder_is_said_plainly_and_nothing_is_read(self):
        with patch.object(hou, "ui", MagicMock(), create=True):
            repair.run(preferences=_NoLibraryPrefs())
            said = " ".join(str(call) for call in hou.ui.displayMessage
                            .call_args_list)
        self.assertIn("no library folder", said.lower())    # case-insensitive: the WORDING is the design's to change, and only the sense is this test's ▸p/messages-need-one-home
        self.assertIn("Preferences", said,
                      "the user is not told where to set one")

    def test_a_library_folder_that_is_not_reachable_is_not_called_absent(
            self):
        prefs = _NoLibraryPrefs()
        prefs.dir = os.path.join(self.dir, "not-mounted") + os.sep
        with patch.object(hou, "ui", MagicMock(), create=True):
            repair.run(preferences=prefs)
            # The arguments, not `str(call)`: a mock repr escapes every backslash.
            said = " ".join(
                str(value)
                for call in hou.ui.displayMessage.call_args_list
                for value in list(call.args) + list(call.kwargs.values()))
        self.assertIn("cannot reach the library folder", said)
        self.assertIn(prefs.dir, said,
                      "the message does not name the folder it cannot "
                      "reach, so nobody can tell which drive to connect")
        self.assertIn("connect it and run Repair again", said)
        self.assertNotIn("has no library folder", said,
                         "an unreachable library is reported as no library "
                         "at all, which is a wrong diagnosis")


class _NoLibraryPrefs:
    dir = ""
    asset_dir = "mat/"
    img_dir = "img/"


class TheWholeFlowTest(_Case):
    """Driving `run` itself: a feature is not verified until its call site is."""

    def _run(self, buttons, listed=None):
        ui = MagicMock()
        ui.displayMessage.side_effect = list(buttons)
        ui.selectFromList.return_value = listed if listed is not None else ()
        with patch.object(hou, "ui", ui, create=True):
            repair.run(preferences=self.prefs)
        return ui

    def test_the_report_is_one_dialog_and_close_changes_nothing(self):
        """Aggregate before interrupting: one dialog, never one per problem."""
        self._cops([])
        paths = self._pair()
        ui = self._run(buttons=[99])          # 99 = the Close button index
        self.assertEqual(1, ui.displayMessage.call_count,
                         "Repair opened more than one dialog to say what it "
                         "found")
        for path in paths:
            self.assertTrue(os.path.exists(path))

    def test_a_panel_that_is_open_stops_it_before_it_reads(self):
        self._cops([])
        tab = MagicMock()
        with patch.object(repair, "open_panel_tab", return_value=tab):
            ui = self._run(buttons=[0])
        said = str(ui.displayMessage.call_args_list[0])
        self.assertIn("Amaze is open", said)
        # Closing a tab does not empty the registry; only a restart does.
        self.assertIn("Quit Houdini", said,
                      "the refusal names a next step that cannot bring the "
                      "buttons back")
        self.assertNotIn("Close Amaze, then run Repair again", said)
        self.assertEqual(1, ui.displayMessage.call_count,
                         "it carried on past the refusal")

    def test_a_session_that_has_read_a_library_gets_the_report_only(self):
        """The guard wired in: `run` is where the decision is made."""
        self._cops([])
        self._write(self.cops + ".bak-1", {"assets": [{"id": "OLD1"}]})
        database.DatabaseConnector("cops.json")     # the panel, earlier
        self.assertTrue(repair.session_has_a_library_open(),
                        "premise: this session must look like one that has "
                        "already opened a library")
        ui = self._run(buttons=[0])
        shown = ui.displayMessage.call_args_list[0]
        self.assertEqual(("Close",), shown[1]["buttons"],
                         "an action was offered to a session whose next "
                         "save would write over it")
        self.assertIn("Quit Houdini", str(shown),
                      "nothing tells the user how to get the buttons back")
        for word in ("session", "index", "record", "row", "database",
                     "merge", "schema", "stale"):
            self.assertNotIn(word, str(shown).lower(),
                             "the dialog uses '%s'" % word)

    def test_the_restore_flow_names_what_it_recovers_and_what_it_loses(self):
        self._cops([{"id": "LIVE1"}, {"id": "LIVE2"}])
        self._write(self.cops + ".bak-1",
                    {"version": 2, "categories": ["_All"], "tags": [],
                     "assets": [{"id": "OLD1"}]})
        # report to the restore button, confirm, done.
        ui = self._run(buttons=[0, 0, 0], listed=(0,))
        confirm = str(ui.displayMessage.call_args_list[1])
        self.assertIn("holds 1 node", confirm,
                      "the confirm does not say what the copy would bring "
                      "back, in the word for what it holds")
        self.assertIn("holds 2", confirm,
                      "the confirm does not say what is there now, so the "
                      "loss cannot be judged")
        self.assertIn("takes you from 2 to 1", confirm,
                      "the confirm gives both numbers and never says what "
                      "the change is")
        self.assertIn("not be there afterwards", confirm)
        self.assertIn("run Repair again", confirm,
                      "the confirm does not say how the restore could be "
                      "undone")
        self.assertEqual(["OLD1"],
                         [r["id"] for r in self._read(self.cops)["assets"]])

    def test_cancelling_the_restore_confirm_changes_nothing(self):
        self._cops([{"id": "LIVE1"}])
        self._write(self.cops + ".bak-1", {"assets": [{"id": "OLD1"}]})
        self._run(buttons=[0, 1], listed=(0,))          # 1 = Cancel
        self.assertEqual(["LIVE1"],
                         [r["id"] for r in self._read(self.cops)["assets"]])
        self.assertEqual(
            [], [name for name in os.listdir(self.dir)
                 if name.startswith("cops.json.bak-before-restore")],
            "a cancelled restore still wrote an undo copy, so it did "
            "something")

    def test_the_quarantine_flow_moves_and_says_where(self):
        self._cops([])
        paths = self._pair()
        findings = self._survey()
        choices, actions = repair._choices(findings, may_change=True)
        index = actions.index("quarantine")
        ui = self._run(buttons=[index, 0, 0])
        for path in paths:
            self.assertFalse(os.path.exists(path))
        told = str(ui.displayMessage.call_args_list[-1])
        self.assertIn("holding folder", told,
                      "the user is not told where the files went")
        self.assertIn("30 days", told,    # the RETENTION, not the words: a destructive-sounding step must promise the files are kept, and saying so positively is the wording rule ▸p/messages-need-one-home
                      "the user is not told the files are kept")


class TheRouteFromCleanLibraryTest(_Case):
    """The step a refusal names must actually work, so the route is tested."""

    def _clean(self, model):
        with patch.object(hou, "ui", MagicMock(), create=True):
            model.cleanup_db(show_dialog=False)

    def _material_model(self):
        from amaze.core import library as library_mod
        return library_mod.MaterialLibrary(preferences=self.prefs)

    def test_the_shelf_carries_a_tool_labelled_exactly_repair(self):
        root = ET.parse(SHELF).getroot()
        tools = {tool.get("name"): tool for tool in root.findall("tool")}
        self.assertIn("amaze_repair_library", tools,
                      "Clean Library sends the user to a tool that is not "
                      "on the shelf")
        tool = tools["amaze_repair_library"]
        self.assertEqual("Repair", tool.get("label"))
        shelves = {shelf.get("name"): [m.get("name") for m in
                                       shelf.findall("memberTool")]
                   for shelf in root.findall("toolshelf")}
        self.assertIn("amaze_repair_library", shelves.get("amaze", []),
                      "the tool exists but is not on the Amaze shelf, so "
                      "the tab the refusal names does not show it")

    def test_the_tab_the_refusal_tells_them_to_add_exists(self):
        """The refusal names a menu entry, so its label has to exist."""
        root = ET.parse(SHELF).getroot()
        labels = [shelf.get("label") for shelf in root.findall("toolshelf")]
        self.assertIn("Amaze", labels)

    def test_the_tool_uses_the_committed_icon_in_the_family(self):
        """The two icons are compared to each other, never to a frozen number."""
        root = ET.parse(SHELF).getroot()
        tool = [t for t in root.findall("tool")
                if t.get("name") == "amaze_repair_library"][0]
        icon = tool.get("icon")
        self.assertEqual(
            "$AMAZE/scripts/python/amaze/ui/icon_repair.svg", icon)
        path = os.path.join(REPO, icon.replace("$AMAZE/", ""))
        self.assertTrue(os.path.isfile(path), "the icon is not committed")

        import re as _re

        def box(svg_path):
            with open(svg_path, encoding="utf-8") as handle:
                found = _re.search(r'viewBox="([^"]+)"', handle.read())
            return found.group(1) if found else None

        mark = os.path.join(REPO, "scripts/python/amaze/ui/logo_mark.svg")
        self.assertEqual(
            box(mark), box(path),
            "icon_repair.svg and logo_mark.svg no longer share a "
            "viewBox - one was restyled without the other, and the "
            "shelf family drifts apart again")

    def test_the_tool_runs_repair_and_guards_its_import(self):
        root = ET.parse(SHELF).getroot()
        tool = [t for t in root.findall("tool")
                if t.get("name") == "amaze_repair_library"][0]
        script = tool.find("script").text
        self.assertIn("from amaze.core import repair", script)
        self.assertIn("except ImportError", script)
        self.assertIn("not importable from this session", script)
        self.assertIn("repair.run()", script)
        # Strip the comments first: a substring test matches the sentence saying so.
        code = "\n".join(line for line in script.splitlines()
                         if not line.strip().startswith("#"))
        self.assertNotIn("panel", code,
                         "the Repair tool reaches for the panel, which is "
                         "the one thing it must not need")

    def test_the_refusal_names_repair_and_repair_then_clears_it(self):
        """The whole route in one test, every step the real code."""
        self._cops([])
        paths = self._pair()
        model = self._material_model()
        self._clean(model)
        summary = " ".join(model.last_cleanup_summary)
        self.assertIn("Repair tool on the Amaze shelf", summary,
                      "the refusal does not name the way out")
        for path in paths:
            self.assertTrue(os.path.exists(path),
                            "Clean Library deleted the files it refused "
                            "over")

        test_support.reset_database_singletons()
        findings = repair.survey(self.dir, self.prefs.asset_dir,
                                 self.prefs.img_dir)
        self.assertEqual(2, repair.unaccounted_total(findings),
                         "Repair does not see what Clean Library refused "
                         "over - the two tools disagree about the folder")
        repair.quarantine(findings)

        test_support.reset_database_singletons()
        again = self._material_model()
        leftover = os.path.join(self.img_dir, "GONEMATERIAL1.png")
        with open(leftover, "wb") as handle:
            handle.write(b"a thumbnail whose material is gone")
        self._clean(again)
        summary = " ".join(again.last_cleanup_summary)
        self.assertNotIn(
            "Amaze could not check", summary,
            "Clean Library still refuses after Repair did everything it "
            "offers - the way out does not work, which is the exact "
            "failure this route was built to avoid")
        self.assertFalse(os.path.exists(leftover),
                         "the sweep reported no refusal and still did not "
                         "run")

    def test_a_later_leftover_goes_through_repair_too_while_a_list_is_empty(
            self):
        """The price of the strict guard: while a section lists nothing, Repair owns it."""
        self._cops([])
        model = self._material_model()
        later = os.path.join(self.mat_dir, "GENUINELEFTOVER2.mat")
        with open(later, "w", encoding="utf-8") as handle:
            handle.write("in no list at all\n")
        self._clean(model)
        self.assertIn("Repair tool on the Amaze shelf",
                      " ".join(model.last_cleanup_summary))
        self.assertTrue(os.path.exists(later),
                        "Clean Library swept it after all, and this test no "
                        "longer describes what the guard does")
        test_support.reset_database_singletons()
        result = repair.quarantine(self._survey())
        self.assertEqual(["GENUINELEFTOVER2.mat"], result["moved"])
        self.assertFalse(os.path.exists(later))

    def test_repair_and_clean_library_count_the_same_files(self):
        """One classifier, two tools: two numbers about one folder is a bug."""
        self._cops([])
        self._pair()
        for name in ("STRAY1.mat.writing", "notes.txt", "STRAY2_cop.mat"):
            with open(os.path.join(self.mat_dir, name), "w",
                      encoding="utf-8") as handle:
                handle.write("x\n")
        model = self._material_model()
        ids = {str(a.mat_id) for a in model.assets}
        clean = model._files_no_section_accounts_for(ids)
        mine = repair.survey(self.dir, self.prefs.asset_dir,
                             self.prefs.img_dir)["unaccounted"][
                                 self.prefs.asset_dir]
        self.assertEqual(sorted(clean), sorted(mine))
        self.assertIn("STRAY2_cop.mat", mine,
                      "premise: a companion file must be in the set, or "
                      "this is not comparing the tail-stripping rule")
        self.assertNotIn("STRAY1.mat.writing", mine,
                         "premise: a scratch file must be out of the set")


class TheRealLibraryRehearsalTest(unittest.TestCase):
    """The same route against the real library's shape, which is only ever read."""

    LISTS = database.DATABASES

    def setUp(self):
        from amaze.prefs import prefs as prefs_mod
        live = test_support.live_library_to_rehearse_on(self)
        self.live = live
        self.dir = tempfile.mkdtemp(prefix="amaze_repair_real_") + os.sep
        self.addCleanup(shutil.rmtree, self.dir, True)
        for name in self.LISTS:
            source = os.path.join(live.dir, name)
            if os.path.exists(source):
                shutil.copy2(source, os.path.join(self.dir, name))
            for tier in restore_lib.TIERS:
                if os.path.exists("%s.%s" % (source, tier)):
                    shutil.copy2("%s.%s" % (source, tier),
                                 os.path.join(self.dir,
                                              "%s.%s" % (name, tier)))
        for folder in (live.asset_dir, live.img_dir):
            os.makedirs(os.path.join(self.dir, folder), exist_ok=True)
            for entry in os.listdir(os.path.join(live.dir, folder)):
                if entry.endswith(".stamp.json"):    # stamps ride WHOLE: the census spares by READING them, and a 0-byte stand-in reads as unreadable and gets swept
                    shutil.copy2(os.path.join(live.dir, folder, entry),
                                 os.path.join(self.dir, folder, entry))
                else:
                    open(os.path.join(self.dir, folder, entry),
                         "wb").close()
        self.prefs = prefs_mod.Prefs()
        self.prefs.dir = self.dir
        self.prefs.path = tempfile.mkdtemp(prefix="amaze_repair_real_prefs_")
        self.addCleanup(shutil.rmtree, self.prefs.path, True)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.mat_dir = os.path.join(self.dir, self.prefs.asset_dir)
        self.cops = os.path.join(self.dir, "cops.json")

    def _survey(self):
        return repair.survey(self.dir, self.prefs.asset_dir,
                             self.prefs.img_dir)

    def _clean(self):
        from amaze.core import library as library_mod
        model = library_mod.MaterialLibrary(preferences=self.prefs)
        with patch.object(hou, "ui", MagicMock(), create=True):
            model.cleanup_db(show_dialog=False)
        return model

    def _cop_ids(self):
        with open(os.path.join(self.live.dir, "cops.json"),
                  encoding="utf-8-sig") as handle:
            return {str(row.get("id"))
                    for row in json.load(handle).get("assets", [])}

    def test_the_real_library_is_coherent_and_sweeps_clean(self):
        """The accept path: if the guard fires here, Clean Library is broken."""
        findings = self._survey()
        self.assertTrue(findings["complete"])
        self.assertEqual(
            0, repair.unaccounted_total(findings),
            "the real library has files no section lists: %r"
            % {folder: names[:5]
               for folder, names in findings["unaccounted"].items()})
        before = len(os.listdir(self.mat_dir))
        model = self._clean()
        self.assertNotIn("Amaze could not check",
                         " ".join(model.last_cleanup_summary))
        self.assertEqual(before, len(os.listdir(self.mat_dir)),
                         "Clean Library deleted files from a library where "
                         "every one of them is listed")

    def test_the_incident_itself_is_refused_and_repair_undoes_it(self):
        """A list seeded over a sync placeholder: refused, named, and put back."""
        owned = sorted(
            name for name in os.listdir(self.mat_dir)
            if database.asset_id_for_file(
                name, repair.ASSET_SIDECARS, "_cop") in self._cop_ids())
        self.assertTrue(owned, "premise: the real cops.json owns files in "
                               "the asset folder")
        with open(self.cops, "w", encoding="utf-8") as handle:
            json.dump({"version": 2, "categories": ["_All"], "tags": [],
                       "assets": []}, handle)

        model = self._clean()
        summary = " ".join(model.last_cleanup_summary)
        self.assertIn("Amaze could not check", summary)
        self.assertIn("Repair tool on the Amaze shelf", summary)
        for name in owned:
            self.assertTrue(
                os.path.exists(os.path.join(self.mat_dir, name)),
                "%s was deleted - this is the 21-file loss, reproduced from "
                "the symptom rather than from the diff" % name)

        findings = self._survey()
        self.assertEqual(
            owned, findings["unaccounted"][self.prefs.asset_dir],
            "Repair does not report the same asset files Clean Library "
            "refused over")
        self.assertGreater(repair.unaccounted_total(findings), len(owned),
                           "the thumbnails those assets own are not "
                           "reported, so the report is narrower than the "
                           "loss was")
        tiers = [tier for tier, _snap in restore_lib.snapshots(self.cops)]
        self.assertIn("bak-1", tiers,
                      "premise: the real cops.json has a saved copy")
        test_support.reset_database_singletons()
        repair.put_back(findings, "cops.json", "bak-1")

        test_support.reset_database_singletons()
        after = self._survey()
        self.assertTrue(after["complete"])
        after_ids = after["ids"]
        still_unlisted = sorted(
            name for name in owned
            if database.asset_id_for_file(
                name, repair.ASSET_SIDECARS, "_cop") not in after_ids)
        self.assertEqual(
            still_unlisted, after["unaccounted"][self.prefs.asset_dir],
            "putting the saved copy back did not account for the files "
            "its rows own, so the recovery does not recover")
        model = self._clean()
        self.assertNotIn("Amaze could not check",
                         " ".join(model.last_cleanup_summary),
                         "Clean Library still refuses after the list was "
                         "put back")


class TestRecoveredRowsAreVisible(unittest.TestCase):
    """A recovered row carries an empty renderer, and the proxy has to show it."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)

    def _proxy(self, renderer_filter):
        proxy = multifilterproxy_model.MultiFilterProxyModel()
        proxy.setSourceModel(self.model)
        proxy.setFilter(self.model.RendererRole, renderer_filter)
        return proxy

    def test_the_fixture_has_the_row_this_is_about(self):
        """Premise: the committed fixture carries the row Repair produces."""
        empties = [a for a in self.model.assets if str(a.renderer) == ""]
        self.assertEqual(1, len(empties),
                         "fixture no longer holds an empty-renderer row, "
                         "so this test proves nothing")

    def test_all_renderers_shows_the_empty_renderer_row(self):
        proxy = self._proxy("all_renderers")
        self.assertEqual(
            self.model.rowCount(), proxy.rowCount(),
            'the Renderer menu says "All" and the grid is still hiding '
            "rows - a Repair-recovered material cannot be seen or "
            "selected, so Edit Info cannot reach it either")

    def test_a_named_renderer_still_excludes_the_empty_row(self):
        """All must not become the only working filter; empty is not MaterialX."""
        proxy = self._proxy("materialx")
        renderers = [
            str(self.model.data(self.model.index(row, 0), self.model.RendererRole))
            for row in range(self.model.rowCount())
        ]
        self.assertEqual(renderers.count("MaterialX"), proxy.rowCount())

    def test_the_sidebar_counter_agrees_with_the_grid(self):
        """The counter mirrors the proxy, or a sidebar 0 sits beside a full grid."""
        cats = category.Categories(preferences=self.prefs)
        cats._renderer_filter = "all_renderers"
        self.assertTrue(
            cats._asset_matches_renderer({"renderer": ""}),
            "sidebar counts an empty-renderer row as invisible while the "
            "grid now shows it")
        cats._renderer_filter = "materialx"
        self.assertFalse(cats._asset_matches_renderer({"renderer": ""}))


class TestLibraryManifest(unittest.TestCase):
    """What a library may contain; `tools/library-audit.py` is the statement."""

    def _audit_module(self):
        import importlib.util
        path = os.path.join(REPO, "tools", "library-audit.py")
        spec = importlib.util.spec_from_file_location("library_audit", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_product_data_is_recognised(self):
        """From `database.DATABASES`: the audit's own list cannot import it."""
        audit = self._audit_module()
        checked = tuple(database.DATABASES) + (
            "policy.json",
            "library.json.bak-1", "cops.json.bak-first",
            "code.json.unreadable", ".amaze_gradient_seed_v1",
            os.path.join("mat", "abc.mat"),
            os.path.join("mat", "abc.interface"),
            os.path.join("img", "abc.png"),
            os.path.join("matX", "pack", "tex.exr"))
        for rel in checked:
            self.assertEqual("ok", audit.classify(rel), rel)

    def test_the_restore_tier_is_never_called_clutter(self):
        """A saved copy is the way home, so it may never classify as junk."""
        audit = self._audit_module()
        for tier in ("bak-1", "bak-2", "bak-3", "bak-first"):
            self.assertEqual("ok", audit.classify("library.json." + tier))

    def test_scratch_and_strangers_are_reported(self):
        audit = self._audit_module()
        for rel, kind in (
                (os.path.join("img", "140024152983962990.png.lock"), "scratch"),
                (os.path.join("mat", "abc.writing"), "scratch"),
                (os.path.join("mat", "abc.mat.capturing"), "scratch"),
                (os.path.join("matX", "pack", "half.tmp"), "scratch"),
                ("stray.txt", "unknown"),
                (os.path.join("mat", "notes.txt"), "unknown"),
                ("notes.md", "unknown"),
                (".DS_Store", "os-noise")):
            self.assertEqual(kind, audit.classify(rel), rel)

    def test_the_committed_fixture_passes_its_own_rule(self):
        audit = self._audit_module()
        fixture = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "assets", "library")
        found = audit.audit(fixture)
        self.assertEqual([], found["scratch"] + found["unknown"],
                         "the fixture library carries files the manifest "
                         "does not allow - fix one or the other")


class TheRebuildDrillTest(unittest.TestCase):
    """Delete the index outright and put the library back from its stamps."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        # One save writes every stamp, and none exists yet.
        self.assertTrue(self.model.save(), "premise: the fixture saves")
        self.mat_dir = os.path.join(self.prefs.dir, self.prefs.asset_dir)

    def _stamps(self):
        return sorted(n for n in os.listdir(self.mat_dir)
                      if n.endswith(library_mod.STAMP_SUFFIX))

    def test_a_stamp_exists_for_every_asset(self):
        self.assertEqual(len(self.model.assets), len(self._stamps()),
                         "an asset has no recovery stamp, so a rebuild "
                         "would silently lose it")

    def test_a_rebuild_leaves_the_other_sections_assets_alone(self):
        """`mat/` is shared by three sections, so a rebuild may not claim it all."""
        import json as json_mod
        mine = {str(a.mat_id) for a in self.model.assets}
        self.assertTrue(mine, "premise: this library has materials")

        stranger = "c0de0000000040008000000000000001"
        with open(os.path.join(self.prefs.dir, self.prefs.asset_dir,
                               stranger + ".stamp.json"), "w",
                  encoding="utf-8") as handle:
            json_mod.dump({"id": stranger, "name": "Jitter Points",
                           "categories": ["Toolbox"], "renderer": "VEX",
                           "code": "// snippet"}, handle)
        with open(os.path.join(self.prefs.dir, "code.json"), "w",
                  encoding="utf-8") as handle:
            json_mod.dump({"version": 2, "categories": ["_All"], "tags": [],
                           "assets": [{"id": stranger}]}, handle)

        rebuilt = repair.rebuild_from_stamps(self.prefs.dir,
                                             self.prefs.asset_dir)

        ids = {str(r.get("id")) for r in rebuilt["assets"]}
        self.assertNotIn(
            stranger, ids,
            "the rebuilt material index claimed a Code snippet")
        self.assertEqual(
            mine, ids,
            "the rebuild did not return exactly this library's own "
            "assets")
        self.assertNotIn(
            "Toolbox", rebuilt["categories"],
            "a category that belongs to Code came with it")

    def test_the_rebuilt_index_carries_this_builds_stamps(self):
        """A rebuild writes this build's schema and its `format` stamp."""
        import json as json_mod
        from amaze import branding

        for name in ("library.json", "library.json.bak-1",
                     "library.json.bak-2", "library.json.bak-3",
                     "library.json.bak-first"):
            path = os.path.join(self.prefs.dir, name)
            if os.path.exists(path):
                os.remove(path)

        ok, sentence = repair.repair_index(self.prefs.dir,
                                           self.prefs.asset_dir)
        self.assertTrue(ok, sentence)
        with open(os.path.join(self.prefs.dir, "library.json"),
                  encoding="utf-8") as handle:
            document = json_mod.load(handle)

        self.assertEqual(
            database.SCHEMA_VERSION, document.get("version"),
            "the rebuilt list under-claims its schema, so every build "
            "runs the whole migration chain over rows already at it")
        self.assertEqual(
            branding.LIBRARY_FORMAT, document.get("format"),
            "the rebuilt list carries no write-protection stamp, so a "
            "build that does not know this format writes it anyway")

    def test_the_index_can_be_rebuilt_after_it_is_deleted(self):
        before = {str(a.mat_id): a.get_as_dict() for a in self.model.assets}
        os.remove(os.path.join(self.prefs.dir, "library.json"))
        self.assertFalse(
            os.path.exists(os.path.join(self.prefs.dir, "library.json")),
            "premise: the index really is gone")

        rebuilt = repair.rebuild_from_stamps(self.prefs.dir,
                                             self.prefs.asset_dir)
        self.assertEqual([], rebuilt["damaged"])
        self.assertEqual(len(before), len(rebuilt["assets"]))

        by_id = {str(r.get("id")): r for r in rebuilt["assets"]}
        self.assertEqual(set(before), set(by_id))
        for mat_id, original in before.items():
            self.assertEqual(
                original, by_id[mat_id],
                "asset %s came back with a different record - the stamp "
                "is not carrying the whole row" % mat_id)

    def test_every_per_asset_FIELD_survives_including_the_soft_ones(self):
        """Ids and names alone are a file listing; the favourite is per-user."""
        row = 1
        asset = self.model.assets[row]
        asset.tags = "brushed,worn"
        asset.description = "a description that lives nowhere else"
        asset.categories = "Metal"
        self.assertTrue(self.model.save())

        os.remove(os.path.join(self.prefs.dir, "library.json"))
        rebuilt = repair.rebuild_from_stamps(self.prefs.dir,
                                             self.prefs.asset_dir)
        back = next(r for r in rebuilt["assets"]
                    if str(r.get("id")) == str(asset.mat_id))
        self.assertEqual("a description that lives nowhere else",
                         back.get("description"))
        self.assertIn("brushed", back.get("tags") or [])
        self.assertIn("Metal", back.get("categories") or [])
        self.assertIn("Metal", rebuilt["categories"])
        self.assertIn("brushed", rebuilt["tags"])

    def test_one_corrupt_stamp_costs_only_its_own_asset(self):
        """The rebuild completes and names the casualty, rather than refusing."""
        stamps = self._stamps()
        self.assertTrue(stamps, "premise: there are stamps to corrupt")
        victim = stamps[0]
        with open(os.path.join(self.mat_dir, victim), "w",
                  encoding="utf-8") as handle:
            handle.write("{ this is not json")

        rebuilt = repair.rebuild_from_stamps(self.prefs.dir,
                                             self.prefs.asset_dir)
        self.assertEqual(len(stamps) - 1, len(rebuilt["assets"]),
                         "a corrupt stamp cost more than its own asset")
        self.assertEqual(
            [victim[: -len(library_mod.STAMP_SUFFIX)]], rebuilt["damaged"],
            "the rebuild did not name the asset it could not recover")

    def test_a_stamp_is_never_read_in_normal_operation(self):
        import ast
        root = os.path.dirname(os.path.dirname(os.path.abspath(
            library_mod.__file__)))
        readers = []
        for folder, _dirs, files in os.walk(root):
            if "tests" in folder.split(os.sep):
                continue
            for name in files:
                if not name.endswith(".py") or name == "repair.py":
                    continue
                full = os.path.join(folder, name)
                with open(full, encoding="utf-8") as fh:
                    text = fh.read()
                if "STAMP_SUFFIX" not in text:
                    continue
                for node in ast.walk(ast.parse(text)):
                    # A read is an `open` naming a stamp, outside the writer itself.
                    if isinstance(node, ast.Call) and \
                            getattr(node.func, "id", "") == "open" and \
                            name not in ("library.py", "repair.py"):
                        readers.append("%s:%d" % (name, node.lineno))
        self.assertEqual([], readers,
                         "something outside Repair reads a recovery stamp - "
                         "they are write-only shadows, and a reader makes "
                         "them a second source of truth")

    def test_a_rebuild_refuses_while_a_sibling_list_is_unreadable(self):
        """An unreadable sibling claims NOTHING, so its assets read as ours."""
        import json as json_mod

        stranger = "c0de0000000040008000000000000002"
        with open(os.path.join(self.mat_dir, stranger + ".stamp.json"), "w",
                  encoding="utf-8") as handle:
            json_mod.dump({"id": stranger, "name": "A COP network",
                           "categories": ["Nodes"]}, handle)
        with open(os.path.join(self.prefs.dir, "cops.json"), "w",  # EXISTS and will not parse - not the absent case ▸p/clean-library-sweep
                  encoding="utf-8") as handle:
            handle.write('{"assets": [{"id": "c0de00000')

        document = repair.rebuild_from_stamps(self.prefs.dir,
                                              self.prefs.asset_dir)
        self.assertEqual(
            ["cops.json"], document["unreadable"],
            "the rebuild did not report the sibling it could not read, so "
            "no caller can refuse on it")

        for name in ("library.json", "library.json.bak-1",
                     "library.json.bak-2", "library.json.bak-3",
                     "library.json.bak-first"):
            path = os.path.join(self.prefs.dir, name)
            if os.path.exists(path):
                os.remove(path)
        ok, sentence = repair.repair_index(self.prefs.dir,
                                           self.prefs.asset_dir)
        self.assertFalse(
            ok, "the index was rebuilt while a sibling could not be read, so "
                "that sibling's assets are now rows in this list")
        self.assertIn("cannot be read", sentence)
        self.assertFalse(
            os.path.exists(os.path.join(self.prefs.dir, "library.json")),
            "a refused rebuild still wrote the index")

    def test_the_damaged_index_is_kept_before_a_rebuild_writes_over_it(self):
        """The dialog promises the corrupted file is retained. It has to be."""
        damaged = b'{"assets": [{"id": "0000000000'
        target = os.path.join(self.prefs.dir, "library.json")
        for name in ("library.json.bak-1", "library.json.bak-2",
                     "library.json.bak-3", "library.json.bak-first"):
            path = os.path.join(self.prefs.dir, name)
            if os.path.exists(path):
                os.remove(path)
        with open(target, "wb") as handle:
            handle.write(damaged)

        ok, sentence = repair.repair_index(self.prefs.dir,
                                           self.prefs.asset_dir)
        self.assertTrue(ok, sentence)

        kept = target + ".unreadable"
        self.assertTrue(
            os.path.exists(kept),
            "the rebuild destroyed the damaged index; no other copy of it "
            "is kept, since the snapshot tier refuses a file that will not "
            "parse")
        with open(kept, "rb") as handle:
            self.assertEqual(damaged, handle.read(),
                             "the kept copy is not the damaged bytes")


class QuarantineIsBoundedTest(unittest.TestCase):
    """A holding folder that only ever grows is a leak wherever it lives."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_quar_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.config = tempfile.mkdtemp(prefix="amaze_quar_cfg_")
        self.addCleanup(shutil.rmtree, self.config, ignore_errors=True)
        real = hostos.config_root
        hostos.config_root = lambda: self.config
        self.addCleanup(setattr, hostos, "config_root", real)

    def _day(self, stamp):
        root = os.path.join(hostos.history_root(
            os.path.join(self.dir, "library.json")),
            library_mod.QUARANTINE_PREFIX, stamp)
        os.makedirs(root, exist_ok=True)
        with open(os.path.join(root, "held.mat"), "w") as fh:
            fh.write("x")
        return root

    def test_the_quarantine_is_not_inside_the_library(self):
        folder = library_mod.quarantine_folder(self.dir)
        self.assertFalse(
            os.path.abspath(folder).startswith(os.path.abspath(self.dir)),
            "the quarantine is inside the library: it would grow there, "
            "sync everywhere, and break the no-temporary-files rule")

    def test_days_past_the_window_are_removed(self):
        import time as _t
        old = _t.strftime("%Y-%m-%d",
                          _t.localtime(_t.time() - 60 * 86400))
        recent = _t.strftime("%Y-%m-%d",
                             _t.localtime(_t.time() - 2 * 86400))
        old_dir, recent_dir = self._day(old), self._day(recent)
        removed = library_mod.prune_quarantine(self.dir)
        self.assertEqual(1, removed)
        self.assertFalse(os.path.exists(old_dir),
                         "a quarantine day past the window survived, so "
                         "the folder grows without end")
        self.assertTrue(os.path.exists(recent_dir),
                        "a recent quarantine day was removed - the window "
                        "is what makes a wrong sweep recoverable")

    def test_the_window_follows_the_NAME_not_mtime(self):
        """A copy rewrites mtime; the name says which day they were taken out."""
        import time as _t
        old = _t.strftime("%Y-%m-%d", _t.localtime(_t.time() - 60 * 86400))
        old_dir = self._day(old)
        os.utime(old_dir, None)              # looks brand new by mtime
        library_mod.prune_quarantine(self.dir)
        self.assertFalse(os.path.exists(old_dir),
                         "pruning followed mtime, so a touched folder "
                         "never expires")

    def test_a_conflicted_copy_is_never_classified_as_sweepable(self):
        """A sync client's rename is the one artifact preserving a divergence."""
        for name in ("library (conflicted copy 2026-07-29).mat",
                     "mat_001 2.mat",
                     "abc-def.mat",
                     "asset.backup.mat"):
            self.assertIsNone(
                database.asset_id_for_file(name, (".mat", ".interface")),
                "%r was classified as sweepable" % name)

    def test_real_shapes_are_still_classified(self):
        """So the strictness cannot be satisfied by refusing everything."""
        for name, want in (
                ("00755b7004824333af08d921462fa3ae.mat",
                 "00755b7004824333af08d921462fa3ae"),
                ("139888336268658010.interface", "139888336268658010"),
                ("COPOWNED1.mat", "COPOWNED1")):
            self.assertEqual(
                want, database.asset_id_for_file(
                    name, (".mat", ".interface")), name)


class DeletingAnAssetActuallyDeletesItTest(unittest.TestCase):
    """The connector unions, so absence is not a delete: it has to be said."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)

    def _ids_on_disk(self):
        with open(os.path.join(self.prefs.dir, "library.json"),
                  encoding="utf-8") as handle:
            return [str(a.get("id")) for a in json.load(handle)["assets"]]

    def test_a_deleted_asset_does_not_come_back(self):
        self.assertTrue(self.model.save(), "premise: the fixture saves")
        victim = str(self.model.assets[0].mat_id)
        self.assertIn(victim, self._ids_on_disk(), "premise: it is on disk")

        self.model.remove_asset(self.model.index(0, 0))
        self.model.save()

        self.assertNotIn(
            victim, self._ids_on_disk(),
            "the deleted material is still in the library - the connector "
            "keeps rows the caller does not mention, so a delete has to be "
            "stated and this one was not")

    def test_it_stays_gone_after_another_save(self):
        """Nor re-adopted from the connector's own copy on the next save."""
        self.test_a_deleted_asset_does_not_come_back()
        gone = self._ids_on_disk()
        self.model.save()
        self.assertEqual(gone, self._ids_on_disk(),
                         "a later save brought the deleted material back")


class DeadScratchesAreSweptWithAnAgeGateTest(unittest.TestCase):
    """The sweep is age-gated: a fresh scratch may be another session's write."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        self.config = tempfile.mkdtemp(prefix="amaze_scr_cfg_")
        self.addCleanup(shutil.rmtree, self.config, True)
        real = hostos.config_root
        hostos.config_root = lambda: self.config
        self.addCleanup(setattr, hostos, "config_root", real)
        self.mat_dir = os.path.join(self.prefs.dir, self.prefs.asset_dir)

    def _scratch(self, name, hours_old):
        full = os.path.join(self.mat_dir, name)
        with open(full, "w") as fh:
            fh.write("partial")
        old = time.time() - hours_old * 3600
        os.utime(full, (old, old))
        return full

    def test_an_old_scratch_is_quarantined_a_fresh_one_kept(self):
        dead = self._scratch("a.mat.xyz123.writing", hours_old=5)
        live = self._scratch("b.mat.abc456.writing", hours_old=0)
        moved = self.model._sweep_dead_scratches(self.mat_dir, [])
        self.assertEqual(1, moved)
        self.assertFalse(os.path.exists(dead),
                         "a five-hour-old scratch survived - they "
                         "accumulate forever after every hard kill")
        self.assertTrue(os.path.exists(live),
                        "a fresh scratch was swept - it may be another "
                        "session's LIVE write")

    def test_the_scratch_lands_in_quarantine_not_nowhere(self):
        self._scratch("c.mat.qqq.writing", hours_old=5)
        names = []
        self.model._sweep_dead_scratches(self.mat_dir, names)
        self.assertEqual(["c.mat.qqq.writing"], names)
        root = os.path.join(hostos.history_root(
            os.path.join(self.prefs.dir, "library.json")),
            library_mod.QUARANTINE_PREFIX)
        held = [f for _r, _d, files in os.walk(root) for f in files]
        self.assertIn("c.mat.qqq.writing", held,
                      "the swept scratch is nowhere - moved means "
                      "recoverable, even for a scratch")

    def test_real_assets_are_never_touched(self):
        before = sorted(os.listdir(self.mat_dir))
        self.model._sweep_dead_scratches(self.mat_dir, [])
        self.assertEqual(before, sorted(os.listdir(self.mat_dir)),
                         "the scratch sweep moved something that is not "
                         "a scratch")


class AFailedPromoteLeavesNoScratchTest(unittest.TestCase):
    """A raising promote must not litter the library - an unowned scratch is how live assets get reported as orphans."""

    def test_write_json_discards_its_scratch_when_the_promote_raises(self):
        folder = tempfile.mkdtemp(prefix="amaze_repair_scratch_")
        self.addCleanup(shutil.rmtree, folder, True)
        target = os.path.join(folder, "library.json")
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("{}")
        with patch.object(hostos, "promote_scratch",
                          side_effect=OSError("no rename")):
            with self.assertRaises(OSError):
                repair._write_json(target, {"assets": []})
        leftovers = [n for n in os.listdir(folder) if ".repairing" in n]
        self.assertEqual([], leftovers,
                         "a failed promote left a scratch behind")
        with open(target, encoding="utf-8") as fh:
            self.assertEqual("{}", fh.read())


class TheSentenceJoinerHasOneOwner(unittest.TestCase):
    """`helpers.and_list`, and `database.py`'s Houdini-free copy of it."""

    def test_it_punctuates_the_way_a_sentence_does(self):
        from amaze.helpers import helpers

        self.assertEqual("", helpers.and_list([]))
        self.assertEqual("a", helpers.and_list(["a"]))
        self.assertEqual("a and b", helpers.and_list(["a", "b"]))
        self.assertEqual("a, b and c", helpers.and_list(["a", "b", "c"]))
        # A generator, not just a list: the call sites pass comprehensions in.
        self.assertEqual("a, b and c",
                         helpers.and_list(x for x in ("a", "b", "c")))

    def test_the_houdini_free_copy_answers_identically(self):
        from amaze.core import database
        from amaze.helpers import helpers

        for words in ([], ["a"], ["a", "b"], ["a", "b", "c", "d"]):
            self.assertEqual(
                helpers.and_list(words), database._and_list(words),
                "the two owners disagree on %r - database.py keeps its "
                "own copy because it must not import hou, which is a "
                "reason to keep it in step, not a reason to forget it"
                % (words,))


if __name__ == "__main__":
    unittest.main(verbosity=2)
