"""The version store: the base files stay the truth, the archive is a
copy of it, and losing versions/ entirely costs nothing but history.
"""

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

from amaze.core import versions  # noqa: E402
from amaze.tests import test_support  # noqa: E402


class _Case(unittest.TestCase):

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        with open(os.path.join(self.prefs.dir, "library.json"),
                  encoding="utf-8") as fh:
            self.mat_id = str(json.load(fh)["assets"][1]["id"])
        self.base_mat = os.path.join(self.prefs.dir,
                                     self.prefs.asset_dir,
                                     self.mat_id + ".mat")

    def _base_bytes(self):
        with open(self.base_mat, "rb") as fh:
            return fh.read()

    def _rewrite_base(self, payload):
        with open(self.base_mat, "wb") as fh:
            fh.write(payload)


class StoreTest(_Case):

    def test_no_versions_is_the_ordinary_state(self):
        self.assertEqual(0, versions.version_count(self.prefs, self.mat_id))
        self.assertEqual([], versions.list_versions(self.prefs, self.mat_id))

    def test_create_archives_the_base_and_becomes_active(self):
        n = versions.create_version(self.prefs, self.mat_id)
        self.assertEqual(1, n)
        self.assertEqual(1, versions.active_version(self.prefs, self.mat_id))
        archived = os.path.join(
            versions.versions_dir(self.prefs, self.mat_id), "1.mat")
        with open(archived, "rb") as fh:
            self.assertEqual(self._base_bytes(), fh.read(),
                             "the archive is not a copy of the base")

    def test_names_default_and_rename_sticks(self):
        versions.create_version(self.prefs, self.mat_id)
        listed = versions.list_versions(self.prefs, self.mat_id)
        self.assertEqual("Version 1", listed[0]["name"],
                         "auto-naming is the recorded rule: never "
                         "interrupt a save to ask for a name")
        self.assertTrue(versions.rename_version(
            self.prefs, self.mat_id, 1, "Hero look"))
        self.assertEqual("Hero look", versions.list_versions(
            self.prefs, self.mat_id)[0]["name"])

    def test_switch_puts_the_archives_bytes_on_the_base(self):
        original = self._base_bytes()
        versions.create_version(self.prefs, self.mat_id)     # V1 = original
        self._rewrite_base(b"EDITED-STATE")
        versions.create_version(self.prefs, self.mat_id)     # V2 = edited

        self.assertTrue(versions.switch_active(self.prefs, self.mat_id, 1))
        self.assertEqual(original, self._base_bytes(),
                         "switching to Version 1 did not restore its "
                         "bytes onto the base - imports would still see "
                         "the edited state")
        self.assertTrue(versions.switch_active(self.prefs, self.mat_id, 2))
        self.assertEqual(b"EDITED-STATE", self._base_bytes())

    def test_a_missing_version_is_refused(self):
        versions.create_version(self.prefs, self.mat_id)
        before = self._base_bytes()
        self.assertFalse(versions.switch_active(self.prefs, self.mat_id, 9))
        self.assertEqual(before, self._base_bytes(),
                         "a refused switch still modified the base")

    def test_losing_the_versions_folder_costs_only_history(self):
        versions.create_version(self.prefs, self.mat_id)
        before = self._base_bytes()
        shutil.rmtree(versions.versions_dir(self.prefs, self.mat_id))
        self.assertEqual(0, versions.version_count(self.prefs, self.mat_id))
        self.assertEqual(before, self._base_bytes(),
                         "the base depended on the archive - it must "
                         "never; the archive is a copy of the truth, "
                         "not the truth")

    def test_an_unreadable_ledger_blocks_writes_not_reads(self):
        versions.create_version(self.prefs, self.mat_id)
        ledger = os.path.join(
            versions.versions_dir(self.prefs, self.mat_id),
            versions.LEDGER)
        with open(ledger, "w", encoding="utf-8") as fh:
            fh.write("{ broken")
        self.assertEqual(0, versions.version_count(self.prefs, self.mat_id))
        self.assertEqual(0, versions.create_version(self.prefs, self.mat_id),
                         "a create wrote blind over an unreadable ledger")
        self.assertFalse(versions.switch_active(self.prefs, self.mat_id, 1))

    def test_the_author_rides_from_prefs_when_chosen(self):
        self.prefs.version_author = "Chosen"
        versions.create_version(self.prefs, self.mat_id)
        self.assertEqual("Chosen", versions.list_versions(
            self.prefs, self.mat_id)[0]["author"])

    def test_no_author_means_empty_never_harvested(self):
        versions.create_version(self.prefs, self.mat_id)
        author = versions.list_versions(self.prefs, self.mat_id)[0]["author"]
        self.assertEqual("", author)


class TheWholeLoopThroughTheModelTest(unittest.TestCase):
    """Parameter-only save -> versions appear; switch -> the base holds
    the old bytes and the next Update Existing is not refused; the
    badge role counts. The chain, not the links."""

    def setUp(self):
        from amaze.core import library as library_mod
        from amaze.core import material as material_mod
        from amaze.render import nodes as nodes_mod
        self.nodes = nodes_mod
        self.material = material_mod
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.model = library_mod.MaterialLibrary(preferences=self.prefs)
        self.staging = hou.node("/obj").createNode("matnet")
        self.addCleanup(self.staging.destroy)
        from amaze.tests.test_roundtrip import _build_material
        self._build = _build_material

    def _karma_row(self):
        return next(r for r in range(self.model.rowCount())
                    if self.material.is_karma_renderer(
                        self.model.assets[r].renderer))

    def test_parameter_only_update_creates_versions(self):
        # A REAL parameter-only edit: import the asset, tweak one float,
        # update. Building a fresh network would be structural.
        row = self._karma_row()
        mat = self.model.assets[row]
        ok, reason = self.model.import_asset_to_scene(
            self.model.index(row, 0), target="mat")
        self.assertTrue(ok, reason)
        imported = next(n for n in hou.node("/mat").children()
                        if n.userData("assetlib_id") == mat.mat_id)
        self.addCleanup(imported.destroy)
        shader = next((c for c in imported.children()
                       if "surface" in c.type().name().lower()
                       or c.type().name().startswith("mtlx")), None)
        if shader is not None:
            scalar = next((parm for parm in shader.parms()
                           if parm.parmTemplate().numComponents() == 1
                           and parm.parmTemplate().type()
                           == hou.parmTemplateType.Float), None)
            if scalar is not None:
                scalar.set(scalar.eval() + 0.2)

        renderer = self.model.update_asset_content(row, imported)
        self.assertTrue(renderer, "premise: the update itself landed")

        from amaze.core import versions as versions_mod
        count = versions_mod.version_count(self.prefs, mat.mat_id)
        self.assertEqual(2, count,
                         "a parameter-only update did not produce the "
                         "pre-edit version and the new one (got %d)"
                         % count)
        self.assertEqual(count, self.model.data(
            self.model.index(row, 0), self.model.VersionsRole),
            "the badge role disagrees with the store")

    def test_switching_back_restores_and_does_not_trip_the_guard(self):
        self.test_parameter_only_update_creates_versions()
        row = self._karma_row()
        mat = self.model.assets[row]
        base = self.model.asset_files(mat.mat_id)["mat"]
        with open(base, "rb") as fh:
            edited = fh.read()

        self.assertTrue(self.model.switch_version(row, 1))
        with open(base, "rb") as fh:
            self.assertNotEqual(edited, fh.read(),
                                "switching to Version 1 left the edited "
                                "bytes on the base")

        # THE GUARD MUST READ OUR OWN SWITCH AS OURS. Without the
        # baseline refresh inside switch_version, the next update reads
        # the switch as another session's write and refuses.
        known = self.model._content_state.get(str(mat.mat_id))
        current = self.model._content_stat(mat.mat_id)
        self.assertEqual(known, current,
                         "switch_version did not rebaseline - the next "
                         "Update Existing will be refused as a conflict")

    def test_a_structural_update_does_not_version(self):
        row = self._karma_row()
        mat = self.model.assets[row]
        fresh = self._build(self.staging, "structural_probe")
        renderer = self.model.update_asset_content(row, fresh)
        self.assertTrue(renderer, "premise: the update landed")
        from amaze.core import versions as versions_mod
        self.assertEqual(0, versions_mod.version_count(
            self.prefs, mat.mat_id),
            "a structural update minted versions - archiving a "
            "different structure under the same history is the lie the "
            "signature exists to prevent")


if __name__ == "__main__":
    unittest.main(verbosity=2)
