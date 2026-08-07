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


class PreEditHoldsTheRightFilesTest(_Case):
    """The first Update on an asset archives the PRE-EDIT state as
    Version 1, from a held-aside copy of the asset's files. The held
    set is keyed by `versions.SOURCE_KINDS`: keying by filename suffix
    collided `<id>_cop.mat` with `<id>.mat` (both ".mat", and the
    companion is listed after the material, so it won the dict) and
    archived the COP companion as Version 1's material - switching
    back then promoted the companion over the material itself. Same
    shape for `<id>_icon.png` standing in for the render."""

    def test_the_material_wins_over_its_companions(self):
        from amaze.core import library as library_mod

        assets_dir = os.path.join(self.prefs.dir, self.prefs.asset_dir)
        img_dir = os.path.join(self.prefs.dir, self.prefs.img_dir)
        os.makedirs(img_dir, exist_ok=True)
        with open(os.path.join(assets_dir, self.mat_id + "_cop.mat"),
                  "wb") as fh:
            fh.write(b"COP-COMPANION-NOT-THE-MATERIAL")
        with open(os.path.join(img_dir, self.mat_id + "_icon.png"),
                  "wb") as fh:
            fh.write(b"ICON-COMPOSITE-NOT-THE-RENDER")

        model = library_mod.MaterialLibrary(preferences=self.prefs)
        held = model._hold_pre_edit_files(self.mat_id)

        with open(held[".mat"], "rb") as fh:
            self.assertEqual(
                self._base_bytes(), fh.read(),
                "the held .mat is not the material - the companion won "
                "the suffix collision and Version 1 archives the wrong "
                "bytes")
        base_png = os.path.join(img_dir, self.mat_id + ".png")
        if os.path.exists(base_png):
            with open(base_png, "rb") as fh:
                base = fh.read()
            with open(held[".png"], "rb") as fh:
                self.assertEqual(
                    base, fh.read(),
                    "the held .png is the icon composite, not the "
                    "render")
        else:
            self.assertNotIn(
                ".png", held,
                "the icon composite stood in for a render the asset "
                "does not have")
        self.assertIn(".interface", held,
                      "the interface never joined the held set")


class SwitchRollsBackOnALedgerRefusal(_Case):
    """switch_active promotes the archive over the base and THEN writes
    the ledger; a refused ledger write left the base holding version N
    while the ledger still named the old one - the exact base/ledger
    disagreement _copy_set's two-phase design exists to prevent, one
    layer up. The previous active's archive is still complete, so the
    rollback is one more promote."""

    def test_the_base_returns_when_the_ledger_will_not_write(self):
        from unittest import mock

        versions.create_version(self.prefs, self.mat_id)          # V1
        self._rewrite_base(b"EDITED-STATE")
        versions.create_version(self.prefs, self.mat_id)          # V2
        with mock.patch.object(versions, "_write_ledger",
                               return_value=False):
            self.assertFalse(
                versions.switch_active(self.prefs, self.mat_id, 1))
        self.assertEqual(
            b"EDITED-STATE", self._base_bytes(),
            "the base holds version 1 while the ledger still names "
            "version 2 - the promotion was not rolled back")


class TheArchiveIsEachVersionsDurableThumbnail(_Case):
    """A version is minted at SAVE time, before that save's render
    lands, so a fresh archive slot starts holding the previous
    version's picture - measured on the real library, where both of a
    material's versions carried byte-identical PNGs. record_render
    runs wherever a row's PNG is declared fresh and copies it into the
    ACTIVE slot, so each version keeps its own picture until the
    version goes."""

    def _png_paths(self):
        img_dir = os.path.join(self.prefs.dir, self.prefs.img_dir)
        os.makedirs(img_dir, exist_ok=True)
        base = os.path.join(img_dir, self.mat_id + ".png")
        folder = versions.versions_dir(self.prefs, self.mat_id)
        return base, folder

    def test_a_fresh_render_lands_in_the_active_slot_only(self):
        base, folder = self._png_paths()
        with open(base, "wb") as fh:
            fh.write(b"V1-RENDER")
        versions.create_version(self.prefs, self.mat_id)          # V1
        self._rewrite_base(b"EDITED-STATE")
        versions.create_version(self.prefs, self.mat_id)          # V2
        # The mint archived V1's picture into V2's slot - the render
        # that will replace it has not landed yet. Now it lands:
        with open(base, "wb") as fh:
            fh.write(b"V2-RENDER-FRESH")
        self.assertTrue(versions.record_render(self.prefs, self.mat_id))
        with open(os.path.join(folder, "2.png"), "rb") as fh:
            self.assertEqual(
                b"V2-RENDER-FRESH", fh.read(),
                "the active slot did not take the fresh render - "
                "switching versions can never change the picture")
        with open(os.path.join(folder, "1.png"), "rb") as fh:
            self.assertEqual(
                b"V1-RENDER", fh.read(),
                "an INACTIVE slot was touched - a render while V2 is "
                "active must never rewrite V1's picture")

    def test_identical_bytes_cost_no_write(self):
        base, folder = self._png_paths()
        with open(base, "wb") as fh:
            fh.write(b"SAME-PICTURE")
        versions.create_version(self.prefs, self.mat_id)
        slot = os.path.join(folder, "1.png")
        before = os.stat(slot).st_mtime_ns
        self.assertTrue(versions.record_render(self.prefs, self.mat_id))
        self.assertEqual(
            before, os.stat(slot).st_mtime_ns,
            "identical bytes were rewritten - every switch would churn "
            "the sync folder")

    def test_no_versions_records_nothing(self):
        base, folder = self._png_paths()
        with open(base, "wb") as fh:
            fh.write(b"PICTURE")
        self.assertFalse(versions.record_render(self.prefs, self.mat_id))
        self.assertFalse(
            os.path.exists(folder),
            "a versions folder appeared for an asset that has no "
            "versions")

    def test_a_missing_base_png_records_nothing(self):
        base, _folder = self._png_paths()
        versions.create_version(self.prefs, self.mat_id)
        # The fixture asset ships a render; the case under test is the
        # asset that has none.
        if os.path.exists(base):
            os.remove(base)
        self.assertFalse(
            versions.record_render(self.prefs, self.mat_id),
            "with no base PNG there is nothing to record, not an "
            "empty file to invent")

    def test_the_model_records_on_every_thumb_refresh(self):
        from amaze.core import library as library_mod

        base, folder = self._png_paths()
        with open(base, "wb") as fh:
            fh.write(b"OLD-PICTURE")
        versions.create_version(self.prefs, self.mat_id)
        with open(base, "wb") as fh:
            fh.write(b"FRESH-PICTURE")
        model = library_mod.MaterialLibrary(preferences=self.prefs)
        row = next(i for i, a in enumerate(model.assets)
                   if str(a.mat_id) == self.mat_id)
        model._add_thumb_paths(model.index(row, 0))
        with open(os.path.join(folder, "1.png"), "rb") as fh:
            self.assertEqual(
                b"FRESH-PICTURE", fh.read(),
                "_add_thumb_paths declared the PNG fresh and the "
                "active slot did not follow")


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
