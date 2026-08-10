"""Repair: the way out of Clean Library's refusal.

Clean Library refuses when it cannot tell a leftover from somebody's
asset, and per practice.md the next step a refusal names has to ACTUALLY
WORK - three refusals have shipped here whose stated remedy could not.
So this file tests the route as well as the tool: the sentence Clean
Library prints, the shelf entry it names, the icon that entry points at,
and the four things Repair can then do.

The load-bearing property is a NEGATIVE one - Repair never deletes - so
it is checked from the source with ast rather than by hoping a test
happens to exercise the branch that would.
"""

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
from amaze.core import library as library_mod             # noqa: E402
from amaze.core import multifilterproxy_model             # noqa: E402
from amaze.helpers import hostos                          # noqa: E402
from amaze.helpers import restore as restore_lib          # noqa: E402
from amaze.tests import test_support                      # noqa: E402

#: repo root: tests -> amaze -> python -> scripts -> repo
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
    """REPORT IN THE USER'S WORDS. A report nobody can act on is a log
    with a dialog around it."""

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
        """The tool the refusal sends people to may not say LESS about an
        empty section than the refusal did - and may not say it twice
        either. Clean Library teaches the ambiguity in one line; so does
        this."""
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
        """The honest half. While a list cannot be read, the union of ids
        is incomplete, so no file may be called unclaimed - and quarantine
        is not offered at all, not merely discouraged."""
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
        """ABSENT IS ONLY "NEW" WHEN NOTHING SAYS THE FILE WAS EVER HERE,
        and Repair asks the same function load() and Clean Library ask."""
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
        # NO FILENAME THE USER HAS NEVER OPENED, unless the message sends
        # them to touch it - and this one does not. "cops.json.bak-1
        # beside it says there was one" also left "beside it" with no
        # antecedent: the list is the thing that is not there. Clean
        # Library names the file, because that message does tell them to
        # remove it.
        self.assertNotIn("cops.json.bak-1", text,
                         "the report names a file the reader has never "
                         "opened in a sentence that does not send them to "
                         "it")

    def test_the_saved_copies_say_what_each_would_bring_back(self):
        """"Which one do I want" cannot be answered from a filename. The
        count and the date are the answer, and they are what the real
        library's copies differ by (measured: cops.json bak-1 8 assets,
        bak-2 6, bak-first 2)."""
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
        # NOT BY TIER. "bak-1" and "bak-first" are storage suffixes the
        # user has never seen on screen, and choosing between them under
        # pressure is guessing.
        for suffix in ("bak-1", "bak-first"):
            self.assertNotIn(suffix, text,
                             "the report asks the reader to choose by "
                             "'%s', which nothing in Houdini has ever "
                             "shown them" % suffix)

    def test_a_copy_that_cannot_be_read_is_not_offered_as_a_rescue(self):
        """A cloud client can truncate the BACKUP too, and a copy listed
        as if it would work is a next step that cannot."""
        self._cops([])
        with open(self.cops + ".bak-1", "w", encoding="utf-8") as handle:
            handle.write("{ truncated")
        findings = self._survey()
        text = "\n".join(repair.report_lines(findings))
        self.assertRegex(text, r"from \d{4}-\d{2}-\d{2} \d\d:\d\d, "
                               r"cannot be read")

    def test_a_colors_file_of_the_wrong_shape_is_not_called_empty(self):
        """A file nothing can be counted in must read as unreadable.
        Calling it empty tells the reader there is nothing here about a
        file that may be full, and that is the sentence that gets a
        library thrown away.

        A LIST document is caught by the count fallback alone, which is
        why this one passed while the sibling below did not. (This
        docstring used to open "the Colors list has its own format and
        no connector" - true until 2026-08-09, and the premise the
        survey's exemption was resting on.)"""
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
        """The shape the count fallback cannot catch, and the one the
        connector actually refuses.

        `count_in` walks the list keys, finds `assets` is not a list,
        finds no mapping payload, and falls through to `len(document),
        "settings"` - so a Colors file that no longer loads answered 1
        and the survey's gradients exemption called it healthy. The
        report then read **Colors - ok, 1 settings** while the section
        was dead in the panel, and no restore was offered for the one
        list that needed it.

        Since 2026-08-09 gradients.json is an ordinary connector
        document with rows under `assets`, so it takes the same shape
        test as the other three."""
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
        """The accept path beside it: taking the exemption away must not
        make every healthy Colors library read as broken."""
        findings = self._survey()
        colors = [e for e in findings["lists"]
                  if e["filename"] == "gradients.json"][0]
        self.assertIn(colors["state"], ("ok", "empty", "absent"),
                      "a healthy Colors list was called %s"
                      % colors["state"])

    def test_a_folder_it_could_not_read_is_not_called_accounted_for(self):
        """A FALSE ALL-CLEAR FROM THE TOOL WHOSE JOB IS TO SAY WHAT IS
        WRONG. With the asset folder not synced down - the most measured
        broken state in this project, the small json arriving before the
        big folder - the report said "every file in the library's own
        folders is accounted for" about a folder nobody had looked in,
        while Clean Library refused outright over the same directory.

        The rule its sibling in library.py already states: a handler that
        returns a neutral value makes a failure indistinguishable from an
        honest empty result."""
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
        """Two buttons acting on two different sets, with nothing saying
        they differ: adding back takes only complete pairs, moving aside
        takes everything unaccounted for. "Unlisted" against "unclaimed"
        read as a synonym rather than as a distinction."""
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
        """practice.md ▸ The user's words, not the program's. These are
        the words that exist only because of how the thing was built."""
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
    """THE ONE PROPERTY THAT MAY NOT REGRESS.

    Checked from the SOURCE rather than by driving branches: a test that
    a particular call did not delete anything proves nothing about the
    branch nobody drove. Parsed with ast, not searched as text - the
    module's own docstring says the words `os.remove` and `shutil.rmtree`
    out loud, and a substring test would fail on the sentence promising
    they are absent (a comment once failed the test that documented the
    fix it described)."""

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
        """ASSERT THE TEST'S OWN PREMISE: the walk has to be able to find
        one, or it is checking nothing."""
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
        """Superseded contract, updated 2026-07-31: Repair used its own
        <library>/_removed_<date>/ while Clean Library used the
        machine-local quarantine - two tools, two answers to "where did
        my file go", and one of them grew inside the synced library
        forever. One location now, with the 30-day window."""
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
        """THE ONE DELETE THAT WAS STILL POSSIBLE IN REPAIR, and no test
        could see it: os.replace OVERWRITES, and the holding folder is
        named per calendar day. The help text invites the exact sequence -
        "you can look through them or drag them back at any time" - so
        drag a file back, let it be written again, run Repair the same
        day, and the first copy's bytes were gone with no message. It is
        none of the calls the no-delete test forbids."""
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
        """It must not become the next Clean Library's problem: the sweep
        lists the asset and image folders, and a top-level folder is not
        in either."""
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
        # The shape has to be the app's own, or the panel meets a row it
        # cannot build. Driven through the real loader, not eyeballed.
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

    def test_only_a_complete_pair_is_offered(self):
        """One half of a pair is not an asset, and a row for it would put
        a tile in the panel that cannot open."""
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
        """`asset_id_for_file` strips the `_cop` tail to get the id, and
        the halves test then reads the extension off the ORIGINAL name -
        so `X_cop.mat` counted as X's `.mat`. With the real `X.mat`
        lost, Add Back mints a row whose material file does not exist:
        the tile-that-cannot-open its own docstring says must never be
        invented, and the next Clean Library reports it as a
        missing-file row forever.

        The identical suffix-vs-kind collision `library.py` records
        having already fixed once in `_hold_pre_edit_files`."""
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
        """The accept path: a genuine pair that HAPPENS to have a COP
        companion beside it must still be reattachable, or the fix
        removes recovery from the assets most worth recovering."""
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
        """The whole point of writing through Material.get_as_dict: a
        hand-assembled row drifts from what the app writes."""
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
        # The undo copy's name is timestamped, never reused - a fixed
        # name made the second restore overwrite the first one's undo.
        self.assertTrue(
            done["undo"].startswith("cops.json.bak-before-restore-"),
            "the undo copy is not named per restore: %r" % done["undo"])
        self.assertEqual(
            [], self._read(os.path.join(self.dir, done["undo"]))["assets"],
            "the list that was there is not in the undo copy, so the "
            "restore cannot be undone")

    def test_the_undo_copy_is_offered_back_and_survives_being_used(self):
        """THE PROMISED UNDO HAS TO BE A COPY THE TOOL WILL OFFER.

        The done-dialog says the list from a moment ago is still there and
        Repair will offer it back. Before this, the undo copy was not among
        the copies snapshots() lists at all, and the only route to it -
        the terminal tool - destroyed it: the undo was a single fixed name
        written BEFORE its source was read, so putting the undo back
        overwrote it with the state it was undoing and then copied that
        over itself. Measured through the shipped CLI: 500 assets, restore
        bak-1 (495), restore bak-before-restore, two successes, and the
        500-asset state gone from the folder."""
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
        # AND THE UNDO'S OWN SOURCE SURVIVES BEING USED. With the fixed
        # name, restoring the undo copy overwrote it before reading it -
        # the one-way door with two names.
        self.assertEqual(
            ["LIVE1", "LIVE2"],
            [r["id"] for r in self._read(
                os.path.join(self.dir, done["undo"]))["assets"]],
            "the undo copy was consumed by being restored, so the same "
            "choice cannot flip back")

    def test_two_restores_in_a_row_keep_the_starting_state(self):
        """THE SECOND RESTORE MUST NOT DELETE WHAT THE FIRST ONE SAVED.
        A fixed undo name meant restore bak-1 then restore bak-2 left the
        starting state nowhere on disk - the exact evening a worried user
        has, trying copies until one looks right. Every restore now writes
        its own timestamped undo copy, so the whole trail stays walkable
        back to the beginning."""
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
        # And the picker offers both, newest first, so the way back to
        # the start is a visible choice rather than an archaeology dig.
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
        """The refusal is shown in a Repair dialog, so it may not read
        "There is no bak-1 copy of library.json to put back" - a storage
        suffix and a file nobody has opened, in a dialog whose every other
        sentence says Nodes and "a copy from 2026-07-27 20:31"."""
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
        """A second implementation of a restore is a second answer. This
        pins that Repair does not have one: the shared function is what
        runs."""
        self._cops([])
        self._write(self.cops + ".bak-1", {"assets": [{"id": "A"}]})
        with patch.object(restore_lib, "put_back",
                          wraps=restore_lib.put_back) as spy:
            repair.put_back(self._survey(), "cops.json", "bak-1")
        self.assertEqual(1, spy.call_count,
                         "Repair restored without going through "
                         "helpers/restore.py")

    def test_a_refusal_carries_no_exception_text_for_the_dialog(self):
        """NO RAW EXCEPTION TEXT ON SCREEN, no Errno, no parse position -
        and the sentence has to be complete without it. The detail rides
        in .detail, where the terminal tool and the log can have it."""
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
    """Repair reports always; it changes only from a session that has not
    opened a library."""

    def test_a_session_that_has_read_a_library_may_not_change_anything(self):
        """load() is gated on `if not self._data`, so a connector that has
        read a list holds that document until the process ends - and its
        next save writes it back over anything put back here. Measured
        from the code, not guessed."""
        self.assertFalse(repair.session_has_a_library_open(),
                         "premise: the registry starts empty")
        connector = database.DatabaseConnector("cops.json")
        self.assertTrue(repair.session_has_a_library_open())
        self.assertIsNotNone(connector)

    def test_the_actions_themselves_refuse_such_a_session(self):
        """THE GUARD IS A PROPERTY OF THE OPERATIONS, NOT OF THE BUTTONS.
        _choices withholding a button protects exactly one caller; any
        other route to these functions - a future menu item, a script,
        the Python shell - would change a library this process is about
        to overwrite from memory. So each action checks for itself, and
        this drives all three with a connector alive."""
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
        """It must work when the panel will not open, which includes
        having no interface at all - this is how the suite runs."""
        self.assertIsNone(repair.open_panel_tab())

    def test_no_library_folder_is_said_plainly_and_nothing_is_read(self):
        with patch.object(hou, "ui", MagicMock(), create=True):
            repair.run(preferences=_NoLibraryPrefs())
            said = " ".join(str(call) for call in hou.ui.displayMessage
                            .call_args_list)
        self.assertIn("no library folder", said)
        self.assertIn("Preferences", said,
                      "the user is not told where to set one")


    def test_a_library_folder_that_is_not_reachable_is_not_called_absent(
            self):
        """NEVER GUESS A CAUSE. One message for both situations told the
        user with an unmounted drive that they had no library and sent
        them to Preferences to pick one - which is how somebody re-points
        Amaze at an empty folder and loses the library from the panel."""
        prefs = _NoLibraryPrefs()
        prefs.dir = os.path.join(self.dir, "not-mounted") + os.sep
        with patch.object(hou, "ui", MagicMock(), create=True):
            repair.run(preferences=prefs)
            # The ARGUMENTS, not str(call). A mock call's repr escapes
            # every backslash, so on Windows the message really did name
            # the folder and the assertion could still never find it -
            # `C:\Users\...` searched inside `C:\\Users\\...`. Reading
            # the args gives the text the user is actually shown.
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
    """Driving run() itself. A feature is not verified until a test drives
    the CALL SITE: 190 tests once passed while a menu action raised on
    click."""

    def _run(self, buttons, listed=None):
        ui = MagicMock()
        ui.displayMessage.side_effect = list(buttons)
        ui.selectFromList.return_value = listed if listed is not None else ()
        with patch.object(hou, "ui", ui, create=True):
            repair.run(preferences=self.prefs)
        return ui

    def test_the_report_is_one_dialog_and_close_changes_nothing(self):
        """AGGREGATE BEFORE INTERRUPTING: one dialog listing what was
        found, never one per problem."""
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
        # THE STEP HAS TO WORK. "Close Amaze, then run Repair again" was
        # the first wording, and closing a tab does not empty the
        # registry: one connector per file lives for the whole process, so
        # the second run landed on the report with no buttons - the user
        # does exactly what they were told and is no better off.
        self.assertIn("Quit Houdini", said,
                      "the refusal names a next step that cannot bring the "
                      "buttons back")
        self.assertNotIn("Close Amaze, then run Repair again", said)
        self.assertEqual(1, ui.displayMessage.call_count,
                         "it carried on past the refusal")

    def test_a_session_that_has_read_a_library_gets_the_report_only(self):
        """The guard WIRED IN, not just callable. run() is where the
        decision is made, and a report that offered a button here would
        put a list back that the next save writes over from memory."""
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
        # The words the style guide bans, checked on the DIALOG this time -
        # report_lines has its own test, and this sentence is added after
        # it, which is exactly where a "session" slips back in.
        for word in ("session", "index", "record", "row", "database",
                     "merge", "schema", "stale"):
            self.assertNotIn(word, str(shown).lower(),
                             "the dialog uses '%s'" % word)

    def test_the_restore_flow_names_what_it_recovers_and_what_it_loses(self):
        self._cops([{"id": "LIVE1"}, {"id": "LIVE2"}])
        self._write(self.cops + ".bak-1",
                    {"version": 2, "categories": ["_All"], "tags": [],
                     "assets": [{"id": "OLD1"}]})
        # report -> "Put a Saved Copy Back" (0), confirm -> button 0, done
        ui = self._run(buttons=[0, 0, 0], listed=(0,))
        confirm = str(ui.displayMessage.call_args_list[1])
        self.assertIn("holds 1 node", confirm,
                      "the confirm does not say what the copy would bring "
                      "back, in the word for what it holds")
        self.assertIn("holds 2", confirm,
                      "the confirm does not say what is there now, so the "
                      "loss cannot be judged")
        # THE SUBTRACTION IS THE DECISION. Two numbers and no arithmetic
        # is what a reader under pressure clicks past; 548 -> 8 is 540
        # gone and the sentence has to say it.
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
        self.assertIn("Nothing was deleted", told)


class TheRouteFromCleanLibraryTest(_Case):
    """THE STEP A REFUSAL NAMES MUST ACTUALLY WORK. Three refusals have
    shipped here whose stated remedy could not, so the route is tested
    end to end: the sentence, the shelf entry it names, the icon that
    entry points at, and whether running it clears the refusal."""

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
        """The refusal says "choose Shelves, then Amaze" - a per-machine
        step (INSTALL.md 6b-2). If the shelf's label ever changed, that
        sentence would name something not in the menu."""
        root = ET.parse(SHELF).getroot()
        labels = [shelf.get("label") for shelf in root.findall("toolshelf")]
        self.assertIn("Amaze", labels)

    def test_the_tool_uses_the_committed_icon_in_the_family(self):
        """The shelf references the committed icon, and the icon shares
        the Amaze mark's viewBox.

        The first version froze the artwork's exact viewBox literal -
        and correctly failed the moment a legitimate design pass
        resized both icons together (2026-07-31, both moved to
        30x30/84 percent fill). A pin on design-owned numbers fails
        every honest art update; what the test actually protects is
        one-sided restyling, and comparing the two files to EACH OTHER
        holds exactly that without freezing either."""
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
        """Follow the two existing tools exactly: a guarded import with a
        readable message when amaze is not importable from that session."""
        root = ET.parse(SHELF).getroot()
        tool = [t for t in root.findall("tool")
                if t.get("name") == "amaze_repair_library"][0]
        script = tool.find("script").text
        self.assertIn("from amaze.core import repair", script)
        self.assertIn("except ImportError", script)
        self.assertIn("not importable from this session", script)
        self.assertIn("repair.run()", script)
        # STRIP THE COMMENTS FIRST. The script's own comment explains that
        # it does not touch the panel, and a bare substring test fails on
        # the sentence documenting the property it is checking - the exact
        # trap practice.md records for source-derived tests.
        code = "\n".join(line for line in script.splitlines()
                         if not line.strip().startswith("#"))
        self.assertNotIn("panel", code,
                         "the Repair tool reaches for the panel, which is "
                         "the one thing it must not need")

    def test_the_refusal_names_repair_and_repair_then_clears_it(self):
        """THE WHOLE ROUTE, in one test. Clean Library refuses and names
        Repair; Repair moves the unclaimed files aside; Clean Library runs
        again. Every step is the real code."""
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

        # The user quits Houdini, starts it again and runs Repair before
        # opening Amaze - the exact step the refusal names. The reset IS
        # that restart: the actions now refuse for themselves while a
        # connector from the refused run is still alive, so a route test
        # that skipped the restart would be driving a flow the tool
        # forbids. Nothing in the route needs a model, which is why the
        # survey is called directly here exactly as run() calls it.
        test_support.reset_database_singletons()
        findings = repair.survey(self.dir, self.prefs.asset_dir,
                                 self.prefs.img_dir)
        self.assertEqual(2, repair.unaccounted_total(findings),
                         "Repair does not see what Clean Library refused "
                         "over - the two tools disagree about the folder")
        repair.quarantine(findings)

        # A fresh session, a fresh model, and the sweep must run now. The
        # leftover proving it ran is an IMAGE: with a section still
        # listing nothing, anything unclaimed in the ASSET folder holds
        # the sweep back again by design - see the test below, which is
        # that consequence pinned rather than discovered later.
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
        """THE PRICE OF THE STRICT GUARD, pinned so nobody meets it as a
        surprise.

        While any section lists nothing, an unclaimed file in the asset
        folder holds the sweep back EVERY time - so for a library with a
        section nobody uses, moving leftovers aside is Repair's job from
        then on, not Clean Library's. That is a real cost and it was
        accepted knowingly: Repair's answer (move aside, keep the bytes,
        never delete) is strictly safer than the one Clean Library would
        have given (unlink), the refusal names it, and it works. What must
        NOT happen is the user being stuck, and they are not."""
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
        # The restart the refusal demands, without which quarantine now
        # refuses this process for itself.
        test_support.reset_database_singletons()
        result = repair.quarantine(self._survey())
        self.assertEqual(["GENUINELEFTOVER2.mat"], result["moved"])
        self.assertFalse(os.path.exists(later))

    def test_repair_and_clean_library_count_the_same_files(self):
        """One classifier, two tools. Two numbers about one folder is its
        own bug, and the number is what the user acts on."""
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
    """The same route against the REAL library's own shape.

    AN INDEPENDENT REPRO FINDS WHAT A FIX'S OWN TESTS CANNOT: the first
    version of the 2026-07-29 fix was sabotage-verified, accept-path
    tested and green, and still deleted the same 23 files. So this
    rebuilds the incident from the symptom instead of from the diff.

    The lists and their saved copies are COPIED; the 1,112 asset files
    and 557 images are reproduced as empty stand-ins with the real names,
    because what every decision here turns on is which id a filename
    belongs to and nothing else. Measured on the real library: 548 + 8 =
    556 .mat files, exactly. The real library is only ever READ.
    """

    LISTS = ("library.json", "cops.json", "code.json", "gradients.json")

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
                open(os.path.join(self.dir, folder, entry), "wb").close()
        self.prefs = prefs_mod.Prefs()
        self.prefs.dir = self.dir
        self.prefs.path = tempfile.mkdtemp(prefix="amaze_repair_real_prefs_")
        self.prefs.legacy_path = ""
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
        """THE ACCEPT PATH ON THE REAL SHAPE. If the guard fires here,
        Clean Library is broken for the only library that exists."""
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
        """cops.json 5,537 bytes / 8 records -> 96 / 0, which is what a
        list seeded over a sync placeholder looks like. 21 files belonging
        to those 8 live assets were deleted. Now: refused, named, and put
        back."""
        owned = sorted(
            name for name in os.listdir(self.mat_dir)
            # Repair's OWN suffix set, imported - the hand-rolled copy
            # here went stale twice (first .stamp.json, then
            # .builder.json), each time on the first real library that
            # had saved under the newer writer.
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
        # The images those assets own are unaccounted for too, and Repair
        # reports them although the guard deliberately does not weigh
        # them (DB-HARDENING step 10 is narrow on purpose). Measured on
        # the real library: 16 asset files plus 7 thumbnails - which is
        # the "23 orphaned file(s) on disk were removed" of the incident,
        # to the file.
        self.assertGreater(repair.unaccounted_total(findings), len(owned),
                           "the thumbnails those assets own are not "
                           "reported, so the report is narrower than the "
                           "loss was")
        tiers = [tier for tier, _snap in restore_lib.snapshots(self.cops)]
        self.assertIn("bak-1", tiers,
                      "premise: the real cops.json has a saved copy")
        # The restart the refusal demands - put_back refuses a Houdini
        # whose connectors still hold the library it is about to change.
        test_support.reset_database_singletons()
        repair.put_back(findings, "cops.json", "bak-1")

        test_support.reset_database_singletons()
        after = self._survey()
        self.assertTrue(after["complete"])
        # bak-1 is OLDER than the newest saves: an asset saved since
        # the last snapshot has no row in the restored list, so its
        # files are - correctly - still reported. A zero expectation
        # here held only for a library that never saved between
        # snapshots; the honest claim is that every file whose row
        # bak-1 DOES hold is accounted again. (put_back saves the
        # pre-restore state first, so the newer rows are one more
        # restore away, not lost.)
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
    """Repair's promise is that you can SEE what it recovered.

    reattach() mints a recovered row with renderer="", and the
    completion dialog tells the user to open Amaze and look in the
    Recovered category. The grid is a PROXY, and the proxy used to
    reject an empty renderer before it reached the all_renderers
    escape - so the row existed, counted in rowCount() on the source
    model, and was invisible under every setting of the Renderer menu.

    The whole suite missed it because no test had ever imported
    multifilterproxy_model: the one model-level repair assertion builds
    a CopLibrary, and the cop proxy carries no renderer filter at all.
    So these drive the MATERIAL proxy specifically, and the sidebar
    counter beside it, since category._asset_matches_renderer promises
    in its docstring to mirror the proxy exactly.
    """

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
        """Premise. The committed fixture carries one renderer="" row -
        the shape Repair produces - so these tests are not inventing a
        case the app cannot reach."""
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
        """The fix must not turn All into the only working filter: an
        empty renderer is not a MaterialX one."""
        proxy = self._proxy("materialx")
        renderers = [
            str(self.model.data(self.model.index(row, 0), self.model.RendererRole))
            for row in range(self.model.rowCount())
        ]
        self.assertEqual(renderers.count("MaterialX"), proxy.rowCount())

    def test_the_sidebar_counter_agrees_with_the_grid(self):
        """category._asset_matches_renderer's docstring promises it
        mirrors the proxy EXACTLY. Fixing one and not the other puts a
        category in the sidebar reading 0 next to a grid showing it."""
        cats = category.Categories(preferences=self.prefs)
        cats._renderer_filter = "all_renderers"
        self.assertTrue(
            cats._asset_matches_renderer({"renderer": ""}),
            "sidebar counts an empty-renderer row as invisible while the "
            "grid now shows it")
        cats._renderer_filter = "materialx"
        self.assertFalse(cats._asset_matches_renderer({"renderer": ""}))


class TestLibraryManifest(unittest.TestCase):
    """What a library may contain, asserted rather than reasoned out.

    Until 2026-07-30 this was written down nowhere, so "is this library
    clean?" got answered by reading the code fresh each time - and the
    first answer given that day was wrong in a way that would have swept
    out the product's own restore tier. tools/library-audit.py is the
    statement; these keep it honest.
    """

    def _audit_module(self):
        import importlib.util
        path = os.path.join(REPO, "tools", "library-audit.py")
        spec = importlib.util.spec_from_file_location("library_audit", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_product_data_is_recognised(self):
        audit = self._audit_module()
        for rel in ("library.json", "cops.json", "code.json",
                    "gradients.json", "policy.json",
                    "library.json.bak-1", "cops.json.bak-first",
                    "code.json.unreadable", ".amaze_gradient_seed_v1",
                    os.path.join("mat", "abc.mat"),
                    os.path.join("mat", "abc.interface"),
                    os.path.join("img", "abc.png"),
                    os.path.join("matX", "pack", "tex.exr")):
            self.assertEqual("ok", audit.classify(rel), rel)

    def test_the_restore_tier_is_never_called_clutter(self):
        """The rule this exists to prevent. A .bak file is how Repair
        gets a library back; classifying it as junk would invite a
        cleanup that removes the only way home."""
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
    """Delete library.json outright and put the library back.

    Before the recovery stamps this was not possible, and it was
    measured rather than assumed: mat/<id>.mat, .interface and
    img/<id>.png carry no tags, no description, no favourite, no date
    and no labelled name or category, so nothing could rebuild an index
    (research.md). The stamps exist to change that answer, and a drill
    that is never run is a claim, not a capability.
    """

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        # One save writes every stamp: they are refreshed after a
        # successful index write, and none exists yet.
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
        """`mat/` is SHARED by Materials, Nodes and Code, so the
        stamps in it belong to three indexes. A rebuild that claims
        all of them hands this one the other sections' assets -
        measured on a real 553-material library holding 580 stamps,
        the other 27 Nodes and Code.

        Asked through database.ids_claimed_by, the same classifier
        Clean Library's pass 3 asks, so the two readers of these
        folders cannot answer it differently.
        """
        import json as json_mod
        mine = {str(a.mat_id) for a in self.model.assets}
        self.assertTrue(mine, "premise: this library has materials")

        # A snippet with a stamp beside the materials', listed only in
        # code.json - exactly what a saved Code asset leaves.
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
        """The stamps a rebuild reads are written by THIS build, so its
        rows are at the current schema - and the document said version 1
        and carried no `format` at all.

        The version is benign only while both migration steps happen to
        be no-ops on already-migrated rows, and Versions is the next
        SCHEMA_VERSION bump. The missing format is not benign now: it is
        the stamp that makes an older build open the library read-only
        and point at the updater, so a rebuilt library invited exactly
        the write the stamp exists to stop."""
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
        """The fields that only the index used to hold. A rebuild that
        returns ids and names but drops tags and favourites is not a
        rebuild, it is a file listing."""
        row = 1
        asset = self.model.assets[row]
        asset.tags = "brushed,worn"
        asset.description = "a description that lives nowhere else"
        asset.fav = True
        asset.categories = "Metal"
        self.assertTrue(self.model.save())

        os.remove(os.path.join(self.prefs.dir, "library.json"))
        rebuilt = repair.rebuild_from_stamps(self.prefs.dir,
                                             self.prefs.asset_dir)
        back = next(r for r in rebuilt["assets"]
                    if str(r.get("id")) == str(asset.mat_id))
        self.assertEqual("a description that lives nowhere else",
                         back.get("description"))
        self.assertTrue(back.get("favorite"))
        self.assertIn("brushed", back.get("tags") or [])
        self.assertIn("Metal", back.get("categories") or [])
        self.assertIn("Metal", rebuilt["categories"])
        self.assertIn("brushed", rebuilt["tags"])

    def test_one_corrupt_stamp_costs_only_its_own_asset(self):
        """The sabotage the plan asks for by name: the rebuild must
        complete and name the casualty, not refuse."""
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
        """Write-only by design: the model must not depend on them.
        Source-derived, because a read added later would be invisible
        to any behavioural test that still passes."""
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
                    # A read is an open() whose argument mentions the
                    # stamp. The writer in library.py opens one too, so
                    # only flag files OTHER than the writer and Repair.
                    if isinstance(node, ast.Call) and \
                            getattr(node.func, "id", "") == "open" and \
                            name not in ("library.py", "repair.py"):
                        readers.append("%s:%d" % (name, node.lineno))
        self.assertEqual([], readers,
                         "something outside Repair reads a recovery stamp - "
                         "they are write-only shadows, and a reader makes "
                         "them a second source of truth")


class QuarantineIsBoundedTest(unittest.TestCase):
    """A holding folder that only ever grows is a slow leak, and moving
    it out of the library relocates that rather than solving it."""

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
        """mtime is rewritten by a backup pass or a file copy; the name
        says which day these files were actually taken out."""
        import time as _t
        old = _t.strftime("%Y-%m-%d", _t.localtime(_t.time() - 60 * 86400))
        old_dir = self._day(old)
        os.utime(old_dir, None)              # looks brand new by mtime
        library_mod.prune_quarantine(self.dir)
        self.assertFalse(os.path.exists(old_dir),
                         "pruning followed mtime, so a touched folder "
                         "never expires")

    def test_a_conflicted_copy_is_never_classified_as_sweepable(self):
        """The case the strict classifier exists for: a sync client's
        rename is the ONE artifact preserving a divergence, and it used
        to read as an unrecognised owner and get swept."""
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
    """The union in DatabaseConnector.set() means absence no longer says
    "remove this" - a row the caller does not mention is kept, because
    it might be a row that caller has simply never heard of. So the
    model has to say a delete out loud, and nothing proved it did:
    removing the forget() call left the whole suite green.
    """

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
        """The row must not be re-adopted from the connector's own copy
        on the next save either."""
        self.test_a_deleted_asset_does_not_come_back()
        gone = self._ids_on_disk()
        self.model.save()
        self.assertEqual(gone, self._ids_on_disk(),
                         "a later save brought the deleted material back")


class DeadScratchesAreSweptWithAnAgeGateTest(unittest.TestCase):
    """Uniquifying the scratch names made leftovers unbounded: a hard
    kill mid-write leaves a fresh <name>.<rand>.writing each time, the
    classifier rightly refuses them, and nothing else ever touched
    them. The sweep is age-gated - a fresh scratch may be a live write
    in another session."""

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


class TheSentenceJoinerHasOneOwner(unittest.TestCase):
    """`helpers.and_list`, and what it must produce.

    It was three functions - `library.py`, `repair.py` and
    `database.py` - two of which are now this one. Nothing asserted the
    joining anywhere: sabotaging it to a plain comma join left
    `test_library` and `test_repair` green, so a shared helper that
    several user-facing sentences run through was pinned by nothing.

    `database.py` keeps a copy on purpose (it is Houdini-free and this
    module imports `hou`), so its answers are checked against this
    one's rather than left to agree by luck.
    """

    def test_it_punctuates_the_way_a_sentence_does(self):
        from amaze.helpers import helpers

        self.assertEqual("", helpers.and_list([]))
        self.assertEqual("a", helpers.and_list(["a"]))
        self.assertEqual("a and b", helpers.and_list(["a", "b"]))
        self.assertEqual("a, b and c", helpers.and_list(["a", "b", "c"]))
        # A generator, not just a list - the call sites pass
        # comprehensions and a sorted() straight in.
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
