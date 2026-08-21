"""tools/upgrade-library.py - the deliberate driver for the migration engine: report touches nothing, --write rehearses on a copy in one FRESH process and runs the real thing in another, refuses loudly (chain gap, newer document, unreadable file, legacy container, lost rows), backs up before acting, and proves the real run against the rehearsal with minted values matched by presence."""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

_TOOL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))),
    "tools", "upgrade-library.py")


def _load_tool():
    spec = importlib.util.spec_from_file_location("upgrade_library", _TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class UpgradeToolCase(unittest.TestCase):

    def setUp(self):
        self.tool = _load_tool()
        self.real_phase = self.tool._phase
        self.tool._phase = self.tool._migrate_inplace  # in-process by default - a subprocess here is a multi-second hython boot per phase; the two tests whose SUBJECT is the process isolation restore the real one
        self.dir = tempfile.mkdtemp(prefix="amaze_upgrade_case_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def _library(self, version=7, assets=None, name="library.json",
                 categories=("_All",), extra=None):
        document = {"version": version, "categories": list(categories),
                    "tags": [], "assets": assets if assets is not None
                    else [{"id": "ok1", "name": "one", "categories": []}]}
        document.update(extra or {})
        with open(os.path.join(self.dir, name), "w",
                  encoding="utf-8") as handle:
            json.dump(document, handle)
        return document

    def _bytes(self, name="library.json"):
        with open(os.path.join(self.dir, name), "rb") as handle:
            return handle.read()

    def _doc(self, name="library.json"):
        with open(os.path.join(self.dir, name), encoding="utf-8") as handle:
            return json.load(handle)

    def _backups(self):
        return [entry for entry in os.listdir(self.dir)
                if entry.startswith("backup-before-")]

    def _run(self, call, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = call(*args)
        return code, out.getvalue()


class TheReportTouchesNothing(UpgradeToolCase):

    def test_a_waiting_upgrade_is_reported_and_nothing_moves(self):
        self._library(version=7)
        before = self._bytes()
        code, out = self._run(self.tool.report, self.dir)
        self.assertEqual(0, code)
        self.assertIn("will climb", out)
        self.assertEqual(before, self._bytes(),
                         "the report changed the file it reported on")

    def test_a_current_library_says_so_in_words(self):
        database = self.tool._connector()
        self._library(version=database.SCHEMA_VERSION)
        code, out = self._run(self.tool.report, self.dir)
        self.assertEqual(0, code)
        self.assertIn("up to date", out)
        self.assertIn("nothing to do", out)

    def test_an_unparseable_database_is_a_refusal_not_a_crash(self):
        with open(os.path.join(self.dir, "library.json"), "w",
                  encoding="utf-8") as handle:
            handle.write("{ not json")
        self.assertEqual(2, self.tool.report(self.dir))

    def test_rows_stranded_in_a_legacy_container_refuse(self):
        self._library(version=4, assets=[], name="gradients.json",
                      extra={"gradients": [{"id": "g1", "name": "dawn"}]})
        code, out = self._run(self.tool.report, self.dir)
        self.assertEqual(2, code)
        self.assertIn("pre-assets container", out)


class TheRehearsalTouchesNothing(UpgradeToolCase):

    def test_a_rehearsal_shows_the_climb_and_writes_nowhere(self):
        self._library(version=7)
        before = self._bytes()
        code, out = self._run(self.tool.rehearse_only, self.dir)
        self.assertEqual(0, code)
        self.assertIn("v7 -> v8", out.replace("None", "8"))
        self.assertEqual(before, self._bytes(),
                         "the rehearsal wrote into the real library")
        self.assertEqual([], self._backups())

    def test_a_document_newer_than_the_build_refuses_here_too(self):
        self._library(version=99)
        code, out = self._run(self.tool.rehearse_only, self.dir)
        self.assertEqual(2, code)
        self.assertIn("NEWER", out)


class TheWriteIsProvenAndBackedUp(UpgradeToolCase):

    def test_a_healthy_library_climbs_behind_a_backup(self):
        self.tool._phase = self.real_phase  # end to end through the real fresh-process phases, once
        self._library(version=7)
        was = self._doc()
        self.assertEqual(0, self.tool.write(self.dir))
        database = self.tool._connector()
        now = self._doc()
        self.assertEqual(database.SCHEMA_VERSION, now["version"])
        self.assertEqual(len(was["assets"]), len(now["assets"]))
        backups = self._backups()
        self.assertEqual(1, len(backups), "one backup for one write")
        with open(os.path.join(self.dir, backups[0], "library.json"),
                  encoding="utf-8") as handle:
            self.assertEqual(7, json.load(handle)["version"],
                             "the backup does not hold the old state")

    def test_a_second_write_does_nothing_and_leaves_no_second_backup(self):
        self._library(version=7)
        self.assertEqual(0, self.tool.write(self.dir))
        self.assertEqual(0, self.tool.write(self.dir))
        self.assertEqual(1, len(self._backups()))

    def test_a_minted_id_is_proven_by_shape_not_bytes(self):
        self._library(version=7, assets=[
            {"name": "orphan", "categories": []},
            {"id": "ok1", "name": "named", "categories": []}])
        self.assertEqual(
            0, self.tool.write(self.dir),
            "a fresh uuid can never equal the rehearsal's, so a "
            "byte-compare here means the mint case always fails")
        rows = self._doc()["assets"]
        self.assertTrue(rows[0].get("id"),
                        "the id-less row was not repaired")

    def test_the_phases_share_no_connector_state(self):
        """Legacy `All` at the head of categories makes load() save mid-migration; with one process for both phases the real run then merged the rehearsal-stamped disk file as a peer and DUPLICATED the id-less row with a second mint."""
        self.tool._phase = self.real_phase
        self._library(version=7, categories=("All", "Warm"), assets=[
            {"name": "orphan", "categories": ["Warm"]},
            {"id": "ok1", "name": "named", "categories": []}])
        self.assertEqual(0, self.tool.write(self.dir))
        rows = self._doc()["assets"]
        self.assertEqual(2, len(rows),
                         "the real run duplicated a row - the phases "
                         "are sharing connector state again")
        self.assertNotIn("All", self._doc()["categories"][1:],
                         "the legacy category rode back in on a merge")

    def test_an_already_current_file_is_not_rewritten(self):
        database = self.tool._connector()
        self._library(version=database.SCHEMA_VERSION, name="cops.json",
                      extra={"format": 2})
        self._library(version=7)
        untouched = self._bytes("cops.json")
        self.assertEqual(0, self.tool.write(self.dir))
        self.assertEqual(untouched, self._bytes("cops.json"),
                         "a database with nothing to do was rewritten, "
                         "spending a backup rotation and a sync upload")
        self.assertEqual(database.SCHEMA_VERSION, self._doc()["version"])

    def test_a_real_run_unlike_the_rehearsal_is_verdict_one(self):
        self._library(version=7)
        honest = self.tool._rehearse
        lying = {"library.json": {
            "lost": 0, "gained": 0, "rows": (1, 1), "versions": (7, 8),
            "changed": [(0, "one", {"name": ("one", "two", True, True)})]}}
        self.tool._rehearse = lambda directory: (lying, {})
        code, out = self._run(self.tool.write, self.dir)
        self.tool._rehearse = honest
        self.assertEqual(1, code)
        self.assertIn("DIFFERS", out)


class EveryRefusalWritesNothing(UpgradeToolCase):

    def test_a_chain_gap_refuses_and_leaves_no_backup(self):
        self._library(version=2)
        before = self._bytes()
        self.assertEqual(2, self.tool.write(self.dir))
        self.assertEqual(before, self._bytes())
        self.assertEqual([], self._backups(),
                         "a refusal left a backup directory behind")

    def test_a_document_newer_than_the_build_is_never_touched(self):
        self._library(version=99)
        before = self._bytes()
        self.assertEqual(2, self.tool.write(self.dir))
        self.assertEqual(before, self._bytes())

    def test_a_lossy_rehearsal_refuses_before_the_backup(self):
        self._library(version=7)
        lossy = {"library.json": {
            "lost": 1, "gained": 0, "changed": [],
            "rows": (1, 0), "versions": (7, 8)}}
        self.tool._rehearse = lambda directory: (lossy, {})
        before = self._bytes()
        self.assertEqual(2, self.tool.write(self.dir))
        self.assertEqual(before, self._bytes())
        self.assertEqual([], self._backups())

    def test_stranded_legacy_rows_refuse_the_write_untouched(self):
        self._library(version=4, assets=[], name="gradients.json",
                      extra={"gradients": [{"id": "g1", "name": "dawn"}]})
        before = self._bytes("gradients.json")
        self.assertEqual(2, self.tool.write(self.dir))
        self.assertEqual(before, self._bytes("gradients.json"))
        self.assertEqual([], self._backups())


if __name__ == "__main__":
    unittest.main()
