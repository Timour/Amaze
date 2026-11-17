"""Write ordering: the database first, the files second, and a failed write deletes nothing."""

import json
import os
import shutil
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import asset_record  # noqa: E402
from amaze.core import library as library_mod  # noqa: E402
from amaze.core import library_files  # noqa: E402
from amaze.core import material  # noqa: E402
from amaze.core import texture_library  # noqa: E402
from amaze.core import versions  # noqa: E402
from amaze.helpers import hostos  # noqa: E402
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
        for mat_id in self._on_disk_ids():
            payload = material.payload_path(self.prefs, mat_id, ".mat",
                                            library_files.MATERIALS)
            if os.path.exists(payload):
                return mat_id
        self.fail("the fixture library has no asset with a payload - this "
                  "test cannot build the conditions it needs")

    def _row(self):
        return self.model.find_asset_row_by_id(self.mat_id)

    def _on_disk_ids(self):
        with open(os.path.join(self.prefs.dir, library_files.MATERIALS),
                  encoding="utf-8") as fh:
            return {str(key) for key in json.load(fh)["assets"]}


class RemoveAssetHonoursTheIndexWrite(_LibraryCase):

    def test_a_refused_write_destroys_nothing_and_the_row_stays(self):
        """Rows and files change together: a failed save moves neither, nor does the next save."""
        versions.create_version(self.prefs, self.mat_id, "V1")
        store = versions.versions_dir(self.prefs, self.mat_id)
        owned = self.model.asset_files(self.mat_id)
        present = [k for k, p in owned.items() if os.path.exists(p)]
        self.assertTrue(present, "the fixture asset owns no files on disk")

        with test_support.full_disk_for(os.path.join(self.prefs.dir, library_files.MATERIALS)):
            self.model.remove_asset(self.model.index(self._row(), 0))

        survivors = [k for k in present if os.path.exists(owned[k])]
        self.assertEqual(sorted(present), sorted(survivors),
                         "remove_asset moved files although the database write failed")
        self.assertTrue(os.path.isdir(store),
                        "the version store was deleted although the delete failed")
        self.assertNotEqual(-1, self.model.find_asset_row_by_id(self.mat_id),
                            "the row left the grid although the delete failed")
        self.assertIn(self.mat_id, self._on_disk_ids(),
                      "materials.json no longer lists an asset whose delete failed")
        self.assertTrue(self.model.save(), "the fixture save should succeed")
        self.assertIn(self.mat_id, self._on_disk_ids(),
                      "the failed delete was carried out by the next save")

    def test_a_completed_delete_removes_the_files_and_the_version_store(self):
        """The fix must not break an ordinary delete."""
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
            "materials/versions/<id>/ outlived the asset. Nothing else removes "
            "it, and its id is now in no database - so no later run can ever "
            "decide it is safe to delete")


class AnIdThatCannotNameAFileOwnsNothing(_LibraryCase):

    ESCAPING = "../../../Documents/thesis"    # Material.from_dict reads ids verbatim, unvalidated

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
        with open(os.path.join(self.prefs.dir, library_files.MATERIALS),
                  encoding="utf-8") as fh:
            doc = json.load(fh)
        self.mat_id = ""
        for mat_id in sorted(doc["assets"]):
            if os.path.exists(material.payload_path(self.prefs, mat_id, ".mat",
                                                    library_files.MATERIALS)):
                self.mat_id = mat_id
                break
        self.assertTrue(self.mat_id, "no fixture asset with a payload")
        self.base = versions._base_paths(self.prefs, self.mat_id)

        self.assertEqual(1, versions.create_version(self.prefs, self.mat_id))
        for kind in (".mat", ".json"):
            self._write(kind, "VERSION-2 %s" % kind)
        self.assertEqual(2, versions.create_version(self.prefs, self.mat_id))

    def _write(self, kind, text):
        """Write `text` as the whole `.mat`, or as the `.json` builder's interface."""
        if kind == ".json":
            asset_record.write_section(self.base[kind], asset_record.BUILDER,
                                       {"type": "subnet", "interface": text, "values": {}})
            return
        with open(self.base[kind], "w", encoding="utf-8") as fh:
            fh.write(text)

    def _text(self, kind):
        if kind == ".json":
            return asset_record.read(self.base[kind])["builder"].get("interface", "")
        with open(self.base[kind], encoding="utf-8") as fh:
            return fh.read(64)

    def _holds(self, kind):
        return 2 if "VERSION-2" in self._text(kind) else 1

    def test_a_held_file_leaves_the_base_on_one_version(self):
        """A sync client with one file open must not leave .mat and .json on different versions."""
        real_promote = hostos.promote_scratch

        def held_record(scratch, target):
            if target.endswith(".json") and self.mat_id in os.path.basename(target):
                raise PermissionError("held by another process")
            return real_promote(scratch, target)

        hostos.promote_scratch = held_record
        self.addCleanup(setattr, hostos, "promote_scratch", real_promote)
        try:
            switched = versions.switch_active(self.prefs, self.mat_id, 1)
        finally:
            hostos.promote_scratch = real_promote

        self.assertTrue(switched, "a recorded switch that waits on one file was reported as failed")
        self._released()
        self.assertEqual(
            self._holds(".mat"), self._holds(".json"),
            "the base is a MIXTURE of two versions: its .mat and its "
            "builder come from different ones, so importing it builds "
            "one version's network behind another's parameters")
        self.assertEqual(self._holds(".mat"), versions.active_version(self.prefs, self.mat_id),
                         "the ledger records another version than the files hold")

    def _released(self):
        """The open file released: `guard.recover` completes the change it journaled."""
        from amaze.core import guard
        guard.Guard(str(self.prefs.dir)).recover()

    def test_an_unarchived_base_is_archived_before_the_switch(self):
        """A structural update makes no version; the base may be the sole copy: archive it first."""
        for kind in (".mat", ".json"):
            self._write(kind, "STRUCTURAL %s" % kind)

        self.assertTrue(versions.switch_active(self.prefs, self.mat_id, 1))
        self.assertEqual(1, self._holds(".mat"))
        self.assertEqual(1, versions.active_version(self.prefs, self.mat_id))

        ledger = versions.read_ledger(self.prefs, self.mat_id)
        archived = []
        for row in ledger["versions"]:
            paths = versions._archive_paths(self.prefs, self.mat_id, row["n"])
            if os.path.exists(paths[".mat"]):
                with open(paths[".mat"], encoding="utf-8") as fh:
                    archived.append(fh.read(64))
        self.assertTrue(
            any("STRUCTURAL" in text for text in archived),
            "the switch destroyed the ONLY copy of the structural "
            "update - no archive holds it: %s" % archived)

    def test_a_held_switch_lands_whole_once_the_file_is_let_go(self):
        """A file kind the base lacked is written with the rest, never alone beside the old ones."""
        os.remove(self.base[".json"])

        real_promote = hostos.promote_scratch

        def held_png(scratch, target):
            if target.endswith(".png") and "/versions/" not in target.replace(os.sep, "/"):    # the base picture
                raise PermissionError("held by another process")
            return real_promote(scratch, target)

        hostos.promote_scratch = held_png
        self.addCleanup(setattr, hostos, "promote_scratch", real_promote)
        try:
            switched = versions.switch_active(self.prefs, self.mat_id, 1)
        finally:
            hostos.promote_scratch = real_promote

        self.assertTrue(switched, "a recorded switch that waits on one file was reported as failed")
        self._released()
        self.assertEqual((1, 1), (self._holds(".mat"), self._holds(".json")),
                         "the switch was applied in part: a material made of two versions")

    def test_an_ordinary_switch_still_works(self):
        self.assertTrue(versions.switch_active(self.prefs, self.mat_id, 1))
        self.assertEqual(1, self._holds(".mat"))
        self.assertEqual(1, self._holds(".json"))
        self.assertEqual(1, versions.active_version(self.prefs, self.mat_id))


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
        """A manifest written just after ours is another writer's, never treated as already read."""
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
        """The fingerprint is of the bytes parsed, so a write made after the parse is merged."""
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
        """`forget` reads the file once and keeps that read's fingerprint, never a second one."""
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
        """Locate Folder stores a trailing slash the manifest keys lack; reconcile must still match."""
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


if __name__ == "__main__":
    unittest.main()
