"""Write ordering - the list first, the files second, and the answer honoured: every test pins a defect reproduced before it was fixed, all one shape, and a reader who breaks one of them should see the others. practice.md ▸ THE LIST IS WRITTEN FIRST"""

import json
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import database  # noqa: E402
from amaze.core import library as library_mod  # noqa: E402
from amaze.core import library_policy  # noqa: E402
from amaze.core import texture_library  # noqa: E402
from amaze.core import versions  # noqa: E402
from amaze.helpers import hostos  # noqa: E402
from amaze.helpers import restore as restore_mod  # noqa: E402
from amaze.tests import test_support  # noqa: E402


class _LibraryCase(unittest.TestCase):
    """A real fixture library and a model over it."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.prefs = test_support.fixture_prefs(self)
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        self.mat_id = self._first_id_with_payload()

    def _first_id_with_payload(self):
        with open(os.path.join(self.prefs.dir, "library.json"),
                  encoding="utf-8") as fh:
            doc = json.load(fh)
        for asset in doc["assets"]:
            mat_id = str(asset.get("id"))
            payload = os.path.join(self.prefs.dir, self.prefs.asset_dir,
                                   mat_id + ".mat")
            if os.path.exists(payload):
                return mat_id
        self.fail("the fixture library has no asset with a payload - this "
                  "test cannot build the conditions it needs")

    def _row(self):
        return self.model.find_asset_row_by_id(self.mat_id)

    def _refuse_the_index_write(self):
        """Point the shared connector at ANOTHER library - the refusal that cannot heal itself: save() returns False at the serves() gate, where setting `_write_blocked` by hand would not work because the merge clears that latch on a healthy file."""
        other = tempfile.mkdtemp(prefix="amaze_other_library_")
        self.addCleanup(shutil.rmtree, other, True)
        shutil.copytree(self.prefs.dir, other, dirs_exist_ok=True)
        database.DatabaseConnector(
            self.model.DB_FILENAME).reload_with_path(other + os.sep)

    def _on_disk_ids(self):
        with open(os.path.join(self.prefs.dir, "library.json"),
                  encoding="utf-8") as fh:
            return {str(a.get("id")) for a in json.load(fh)["assets"]}


class RemoveAssetHonoursTheIndexWrite(_LibraryCase):

    def test_a_refused_write_destroys_nothing_and_the_row_stays(self):
        """The forget mark outlives a refused save: without unforget() the next save deletes the row."""
        versions.create_version(self.prefs, self.mat_id, "V1")
        store = versions.versions_dir(self.prefs, self.mat_id)
        owned = self.model.asset_files(self.mat_id)
        present = [k for k, p in owned.items() if os.path.exists(p)]
        self.assertTrue(present, "the fixture asset owns no files on disk")

        self._refuse_the_index_write()
        self.model.remove_asset(self.model.index(self._row(), 0))

        survivors = [k for k in present if os.path.exists(owned[k])]
        self.assertEqual(
            sorted(present), sorted(survivors),
            "remove_asset destroyed payload files even though the library "
            "list write was refused - these files have no .bak tier and no "
            "quarantine copy, so they are gone for good")
        self.assertTrue(os.path.isdir(store),
                        "the version store was destroyed although the "
                        "delete was refused")
        self.assertNotEqual(
            -1, self.model.find_asset_row_by_id(self.mat_id),
            "the row was dropped from the grid although the delete was "
            "refused - the tile vanishes and comes back on the next launch")
        self.assertIn(
            self.mat_id, self._on_disk_ids(),
            "library.json no longer lists an asset whose delete was refused")

        database.DatabaseConnector(    # point the connector home again and save normally
            self.model.DB_FILENAME).reload_with_path(self.prefs.dir)
        self.assertTrue(self.model.save(), "the fixture save should succeed")
        self.assertIn(
            self.mat_id, self._on_disk_ids(),
            "the refused delete was carried out by the next save - the "
            "forget mark was never taken back")

    def test_a_refused_write_leaks_no_row_into_the_other_library(self):
        """The restore's set() lands on the shared connector, which a refusal at the serves() gate means is bound to ANOTHER pane's library - the put-back row must not be absorbed into that library's live document."""
        other = tempfile.mkdtemp(prefix="amaze_other_library_")
        self.addCleanup(shutil.rmtree, other, True)
        shutil.copytree(self.prefs.dir, other, dirs_exist_ok=True)
        index_path = os.path.join(other, "library.json")
        with open(index_path, encoding="utf-8") as fh:
            doc = json.load(fh)
        doc["assets"] = [a for a in doc["assets"]
                         if str(a.get("id")) != self.mat_id]
        with open(index_path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        connector = database.DatabaseConnector(self.model.DB_FILENAME)
        connector.reload_with_path(other + os.sep)

        self.model.remove_asset(self.model.index(self._row(), 0))

        listed = {str(a.get("id"))
                  for a in connector._data.get("assets", [])}
        self.assertNotIn(
            self.mat_id, listed,
            "the refused delete's restore injected the row into the "
            "OTHER library's live document - its payload files live in "
            "this one, so that library now lists a fileless asset")

    def test_a_completed_delete_removes_the_files_and_the_version_store(self):
        """The fix must not cost the ordinary case."""
        number = versions.create_version(self.prefs, self.mat_id, "V1")
        store = versions.versions_dir(self.prefs, self.mat_id)
        self.assertTrue(number and os.path.isdir(store),
                        "could not build a version store to delete")
        owned = self.model.asset_files(self.mat_id)
        present = [k for k, p in owned.items() if os.path.exists(p)]
        self.model.remove_asset(self.model.index(self._row(), 0))

        left = [k for k in present if os.path.exists(owned[k])]
        self.assertEqual([], left,
                         "a successful delete left payload files behind")
        self.assertNotIn(self.mat_id, self._on_disk_ids())
        self.assertFalse(
            os.path.isdir(store),
            "mat/versions/<id>/ survived the asset. Nothing else removes "
            "it, and its id is now in no list - so no later run can ever "
            "decide it is safe to take")


class AnIdThatCannotNameAFileOwnsNothing(_LibraryCase):

    ESCAPING = "../../../Documents/thesis"    # read verbatim out of library.json by Material.from_dict, which validates nothing - a hand-edited, tampered or badly-merged index

    def test_an_escaping_id_owns_nothing_and_a_real_one_stays_inside(self):
        self.assertEqual({}, self.model.asset_files(self.ESCAPING))
        self.assertEqual({}, self.model.asset_directories(self.ESCAPING))
        root = os.path.realpath(self.prefs.dir)
        for kind, path in self.model.asset_files(self.mat_id).items():
            self.assertTrue(
                os.path.realpath(path).startswith(root),
                "%s resolved outside the library: %s" % (kind, path))


class SwitchingVersionsIsAllOrNothing(unittest.TestCase):

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.prefs = test_support.fixture_prefs(self)
        with open(os.path.join(self.prefs.dir, "library.json"),
                  encoding="utf-8") as fh:
            doc = json.load(fh)
        self.mat_id = ""
        for asset in doc["assets"]:
            mat_id = str(asset.get("id"))
            if os.path.exists(os.path.join(self.prefs.dir,
                                           self.prefs.asset_dir,
                                           mat_id + ".mat")):
                self.mat_id = mat_id
                break
        self.assertTrue(self.mat_id, "no fixture asset with a payload")
        self.base = versions._base_paths(self.prefs, self.mat_id)

        self.assertEqual(1, versions.create_version(self.prefs, self.mat_id))
        for kind in (".mat", ".interface"):
            with open(self.base[kind], "w", encoding="utf-8") as fh:
                fh.write("VERSION-2 %s" % kind)
        self.assertEqual(2, versions.create_version(self.prefs, self.mat_id))

    def _holds(self, kind):
        with open(self.base[kind], encoding="utf-8") as fh:
            return 2 if "VERSION-2" in fh.read(64) else 1

    def test_a_held_file_leaves_the_base_on_one_version(self):
        """The realistic failure - a sync client holds one file: measured before the fix, .mat on version 1, .interface on version 2, the ledger naming a third state, and nothing able to see the disagreement."""
        real_promote = hostos.promote_scratch

        def held_interface(scratch, target):
            if target.endswith(".interface"):
                raise PermissionError("held by another process")
            return real_promote(scratch, target)

        hostos.promote_scratch = held_interface
        self.addCleanup(setattr, hostos, "promote_scratch", real_promote)
        try:
            switched = versions.switch_active(self.prefs, self.mat_id, 1)
        finally:
            hostos.promote_scratch = real_promote

        self.assertFalse(switched, "switch_active reported success")
        self.assertEqual(
            self._holds(".mat"), self._holds(".interface"),
            "the base is a MIXTURE of two versions: its .mat and its "
            ".interface come from different ones, so importing it builds "
            "one version's network behind another's parameters")

    def test_an_unarchived_base_is_archived_before_the_switch(self):
        """A STRUCTURAL update rewrites the base without minting a version (the no-mint rule) - so at switch time the base can hold the only copy of that content, and promoting an archive over it destroys it. The docstring's promise: the base is archived first."""
        for kind in (".mat", ".interface"):
            with open(self.base[kind], "w", encoding="utf-8") as fh:
                fh.write("STRUCTURAL %s" % kind)

        self.assertTrue(versions.switch_active(self.prefs, self.mat_id, 1))
        self.assertEqual(1, self._holds(".mat"))
        self.assertEqual(1, versions.active_version(self.prefs, self.mat_id))

        ledger = versions.read_ledger(self.prefs, self.mat_id)
        archived = []
        for row in ledger["versions"]:
            paths = versions._archive_paths(self.prefs, self.mat_id,
                                            versions._row_stem(row))
            if os.path.exists(paths[".mat"]):
                with open(paths[".mat"], encoding="utf-8") as fh:
                    archived.append(fh.read(64))
        self.assertTrue(
            any("STRUCTURAL" in text for text in archived),
            "the switch destroyed the ONLY copy of the structural "
            "update - no archive holds it: %s" % archived)

    def test_a_failed_switch_removes_the_kinds_it_created(self):
        """The rollback restores displaced targets - a kind promoted onto a target that did NOT previously exist must be taken back too, or the base pairs one version's material with another's interface."""
        os.remove(self.base[".interface"])

        real_promote = hostos.promote_scratch

        def held_png(scratch, target):
            if target.endswith(".png") and "/img" in target.replace(os.sep, "/"):    # the img dir is joined with `/`, so a Windows path is mixed
                raise PermissionError("held by another process")
            return real_promote(scratch, target)

        hostos.promote_scratch = held_png
        self.addCleanup(setattr, hostos, "promote_scratch", real_promote)
        try:
            switched = versions.switch_active(self.prefs, self.mat_id, 1)
        finally:
            hostos.promote_scratch = real_promote

        self.assertFalse(switched, "premise: the held file refuses the switch")
        self.assertFalse(
            os.path.exists(self.base[".interface"]),
            "the failed switch left version 1's .interface beside the "
            "restored base .mat - a material made of two versions")

    def test_an_ordinary_switch_still_works(self):
        self.assertTrue(versions.switch_active(self.prefs, self.mat_id, 1))
        self.assertEqual(1, self._holds(".mat"))
        self.assertEqual(1, self._holds(".interface"))
        self.assertEqual(1, versions.active_version(self.prefs, self.mat_id))


class AnAbsentPolicyIsNotAPermissiveOne(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_policy_case_")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_absent_with_a_trace_fails_closed_and_without_one_is_a_new_library(self):
        self.assertTrue(
            library_policy.allow_overwrite(self.dir),
            "a library that never had a policy must not be treated as a "
            "restrictive one - that would make every new library refuse "
            "Update Existing")
        library_policy.set_allow_overwrite(self.dir, True)    # twice, so snapshot_before_write has something to copy - what the real library looks like; a one-write library has no trace and the permissive default is then correct
        library_policy.set_allow_overwrite(self.dir, False)
        traces = [n for n in os.listdir(self.dir)
                  if n.startswith("policy.json.")]
        self.assertTrue(traces, "no backup was written to be a trace")

        os.remove(os.path.join(self.dir, "policy.json"))

        self.assertFalse(
            library_policy.allow_overwrite(self.dir),
            "a momentarily absent policy.json turned overwrite protection "
            "back ON while its own backups sat beside it")


class TheThumbnailManifestKeepsAnotherWritersWork(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="amaze_texcache_case_")
        self.addCleanup(shutil.rmtree, self.root, True)
        hostos.set_cache_override(self.root)
        self.addCleanup(hostos.set_cache_override, "")

    def test_a_second_writer_does_not_clobber_the_first(self):
        tab_a = texture_library.ThumbnailCache(size=256)
        tab_b = texture_library.ThumbnailCache(size=256)

        for n in range(30):
            tab_a._manifest["/textures/wood/%d.exr" % n] = {"mtime": 1,
                                                            "size": 1}
        tab_a._dirty = True
        tab_a.save()

        tab_b._manifest["/textures/metal/1.exr"] = {"mtime": 1, "size": 1}
        tab_b._dirty = True
        tab_b.save()

        with open(tab_b.manifest_path, encoding="utf-8") as fh:
            final = json.load(fh)
        kept = [k for k in final if "/wood/" in k]
        self.assertEqual(
            30, len(kept),
            "the second writer replaced the first writer's entries - those "
            "PNGs are still on disk and nothing will ever find them again, "
            "so the folder re-converts from scratch on every visit")

    def test_entries_written_right_after_our_save_survive_the_next(self):
        """A manifest landing just after our write is another writer's, never taken as seen."""
        cache = texture_library.ThumbnailCache(size=256)
        cache._manifest["/textures/wood/1.exr"] = {"mtime": 1, "size": 1}
        cache._dirty = True
        disarm = self._theirs_land_after(hostos, "write_json_atomic",
                                         cache.manifest_path)
        cache.save()
        disarm()
        self.assertEqual(3, self._saved_metal(cache),
                         "the entries another writer saved right after ours "
                         "were dropped by our next save, orphaning their PNGs")

    def _theirs_land_after(self, owner, name, path):
        theirs = {"/textures/metal/%d.exr" % n: {"mtime": 1, "size": 1}
                  for n in range(3)}
        real, armed = getattr(owner, name), [True]

        def then_theirs_land(*args, **kwargs):
            answer = real(*args, **kwargs)
            if armed[0]:
                armed[0] = False
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(theirs, fh)
            return answer

        setattr(owner, name, then_theirs_land)
        self.addCleanup(setattr, owner, name, real)
        return lambda: setattr(owner, name, real)

    def _saved_metal(self, cache):
        cache._manifest["/textures/wood/2.exr"] = {"mtime": 1, "size": 1}
        cache._dirty = True
        cache.save()
        with open(cache.manifest_path, encoding="utf-8") as fh:
            return len([k for k in json.load(fh) if "/metal/" in k])

    def test_entries_written_while_the_manifest_loads_survive_our_save(self):
        """The fingerprint is of the bytes parsed, so a write landing after the parse is merged."""
        path = texture_library.ThumbnailCache(size=256).manifest_path
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"/textures/wood/1.exr": {"mtime": 1, "size": 1}}, fh)
        disarm = self._theirs_land_after(json, "loads", path)
        cache = texture_library.ThumbnailCache(size=256)
        disarm()
        self.assertEqual(3, self._saved_metal(cache),
                         "the entries written while the manifest loaded "
                         "were dropped by our save")

    def test_entries_written_while_a_sweep_is_forgotten_survive_our_save(self):
        """A forget adopts the file once and keeps that read's fingerprint, never a second one."""
        cache = texture_library.ThumbnailCache(size=256)
        cache._manifest["/textures/wood/1.exr"] = {"mtime": 1, "size": 1}
        cache._dirty = True
        cache.save()
        disarm = self._theirs_land_after(hostos, "peer_read",
                                         cache.manifest_path)
        cache.forget(["/textures/wood/1.exr"])
        disarm()
        self.assertEqual(3, self._saved_metal(cache),
                         "the entries written while a sweep was forgotten "
                         "were dropped by our save")

    def test_reconcile_matches_a_folder_stored_with_a_trailing_slash(self):
        """Locate Folder GUARANTEES the trailing slash the manifest's canonicalised keys lack - the two never matched, so a relocated folder was never reconciled again."""
        images = os.path.join(self.root, "images")
        os.makedirs(images)
        live = os.path.join(images, "keep.png")
        open(live, "w").close()

        cache = texture_library.ThumbnailCache(size=256)
        stat = os.stat(live)
        cache._manifest[hostos.canonical_path_key(live)] = {
            "mtime": stat.st_mtime, "size": stat.st_size}
        deleted = hostos.canonical_path_key(
            os.path.join(images, "deleted.png"))
        cache._manifest[deleted] = {"mtime": 1, "size": 1}

        cache.reconcile_many({images + os.sep: ["keep.png"]})

        self.assertNotIn(
            deleted, cache._manifest,
            "the entry for a file that no longer exists survived, because "
            "the folder's stored path ends in a separator")
        self.assertIn(hostos.canonical_path_key(live), cache._manifest,
                      "reconcile dropped a live file's thumbnail")


class TheUndoCopyBoundHoldsWithoutHoudini(unittest.TestCase):
    """The retirement of old undo copies once reached quarantine_file through a hou-importing module, so from the terminal tool the bound retired nothing - pinned in two halves: the bound RETIRES, and the module it retires through stays free of hou."""

    def test_the_bound_retires_the_oldest_copies(self):
        root = tempfile.mkdtemp(prefix="amaze_restore_case_")
        self.addCleanup(shutil.rmtree, root, True)
        target = os.path.join(root, "library.json")
        open(target, "w").close()
        over = restore_mod.KEEP_UNDO_COPIES + 3
        for n in range(over):
            name = "%s.bak-before-restore-202608%02d-120000" % (target,
                                                                n + 1)
            with open(name, "w", encoding="utf-8") as fh:
                fh.write("state %d" % n)

        retired = restore_mod._retire_old_undo_copies(target)

        left = [n for n in os.listdir(root)
                if ".bak-before-restore-" in n]
        self.assertEqual(
            restore_mod.KEEP_UNDO_COPIES, len(left),
            "the bound retired %d of %d - every restore mints a full copy "
            "of the library index inside the synced folder, so a family "
            "that is never retired grows without limit"
            % (len(retired), over))
        self.assertTrue(retired, "nothing was reported as retired")

    def test_the_retirement_does_not_go_through_a_hou_importing_module(self):
        """The regression guard a behaviour test cannot be: under hython the hou import succeeds, so pointing the retirement back at it would leave the test above green and the terminal tool broken again."""
        source = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "helpers", "restore.py")
        with open(source, encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn(
            "from amaze.core import library", text,
            "helpers/restore.py imports core/library.py, which imports "
            "hou - so this code path dies in the pure-stdlib terminal tool")

        quarantine_source = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "core", "quarantine.py")
        with open(quarantine_source, encoding="utf-8") as fh:
            quarantine_text = fh.read()
        for line in quarantine_text.splitlines():
            self.assertFalse(
                line.strip().startswith(("import hou", "from hou")),
                "core/quarantine.py imports hou (%r) - the terminal "
                "restore tool cannot reach it any more" % line.strip())


class UndoCopiesAreOrderedByTheirName(unittest.TestCase):

    def test_the_picker_and_the_retirement_agree(self):
        """mtime says when a file was TOUCHED; the name says which state it holds, and a backup pass rewrites the former."""
        root = tempfile.mkdtemp(prefix="amaze_undo_order_")
        self.addCleanup(shutil.rmtree, root, True)
        target = os.path.join(root, "library.json")
        open(target, "w").close()
        stamps = ["20260801-120000", "20260802-120000", "20260803-120000"]
        for stamp in stamps:
            name = "%s.bak-before-restore-%s" % (target, stamp)
            with open(name, "w", encoding="utf-8") as fh:
                fh.write(stamp)
        os.utime("%s.bak-before-restore-%s" % (target, stamps[0]),    # the oldest STATE, touched most recently - what any backup pass or transport produces
                 (2 ** 31 - 1, 2 ** 31 - 1))

        found = restore_mod.snapshots(target)
        undos = [tier for tier, _path in found
                 if "bak-before-restore-" in tier]
        self.assertTrue(undos, "no undo copies were surveyed")
        self.assertIn(
            stamps[-1], undos[0],
            "the picker called the oldest state the newest, because it "
            "sorted by mtime while the retirement sorts by name - so the "
            "copy offered first is not the one being kept")


if __name__ == "__main__":
    unittest.main()
