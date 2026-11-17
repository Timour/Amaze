"""The version store: the base files are the current asset; losing versions/ loses only history."""

import json
import os
import shutil
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402,F401

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.core import asset_record, library_files, material, versions  # noqa: E402
from amaze.actions import materials as material_actions  # noqa: E402
from amaze.tests import test_support  # noqa: E402

MATERIALS = library_files.MATERIALS


class _Case(unittest.TestCase):

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        with open(os.path.join(self.prefs.dir, library_files.MATERIALS),
                  encoding="utf-8") as fh:
            self.mat_id = sorted(key for key in json.load(fh)["assets"] if key != "-1")[0]
        self.base_mat = material.payload_path(self.prefs, self.mat_id, ".mat", MATERIALS)
        self.base_record = asset_record.path_for(self.prefs, self.mat_id, MATERIALS)
        self.base_png = os.path.join(material.section_folder(self.prefs.dir, MATERIALS),
                                     self.mat_id + ".png")    # the asset's one picture

    def _base_builder(self):
        return asset_record.read(self.base_record)[asset_record.BUILDER]

    def _set_base_builder(self, interface):
        asset_record.write_section(self.base_record, asset_record.BUILDER,
                                   {"type": "subnet", "interface": interface, "values": {}})

    def _base_bytes(self):
        with open(self.base_mat, "rb") as fh:
            return fh.read()

    def _rewrite_base(self, payload):
        with open(self.base_mat, "wb") as fh:
            fh.write(payload)


class PreEditHoldsTheRightFilesTest(_Case):
    """The pre-edit hold is keyed by `versions.SOURCE_KINDS`, never by filename suffix."""

    def test_the_material_wins_over_its_companions(self):
        from amaze.core import library as library_mod

        assets_dir = material.section_folder(self.prefs.dir, MATERIALS)
        img_dir = os.path.join(self.prefs.dir, self.prefs.img_dir)
        os.makedirs(img_dir, exist_ok=True)
        with open(os.path.join(assets_dir, self.mat_id + "_cop.mat"),
                  "wb") as fh:
            fh.write(b"COP-COMPANION-NOT-THE-MATERIAL")
        with open(os.path.join(img_dir, self.mat_id + "_icon.png"),
                  "wb") as fh:    # a format 3 composite left behind, never the picture
            fh.write(b"ICON-COMPOSITE-NOT-THE-RENDER")

        model = library_mod.MaterialLibrary(preferences=self.prefs)
        held = model._hold_pre_edit_files(self.mat_id)

        with open(held[".mat"], "rb") as fh:
            self.assertEqual(
                self._base_bytes(), fh.read(),
                "the held .mat is not the material - the companion was picked in "
                "the suffix collision and Version 1 archives the wrong "
                "bytes")
        base_png = self.base_png
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
                "the icon composite was used as a render the asset "
                "does not have")
        self.assertIn(".json", held,
                      "the builder record is not in the held set")
        self.assertNotIn(".interface", held,
                         "a converted asset held a format 3 .interface it does not own")


class APreEditHoldLeavesNoFolderBehind(_Case):
    """The hold's temp folder is removed when it holds nothing, and when a copy into it fails."""

    def _holding(self, mat_id, copyfile=shutil.copyfile):
        """What `_hold_pre_edit_files` returned or raised, and what it left in the temp folder."""
        import tempfile
        from unittest import mock
        from amaze.core import library as library_mod

        model = library_mod.MaterialLibrary(preferences=self.prefs)
        temp = test_support.scratch_dir("amaze_preedit_parent_")
        self.addCleanup(shutil.rmtree, temp, True)
        with mock.patch.object(tempfile, "tempdir", temp), \
                mock.patch.object(shutil, "copyfile", copyfile):
            try:
                answer = model._hold_pre_edit_files(mat_id)
            except OSError as exc:
                answer = exc
        return answer, os.listdir(temp)

    def test_nothing_to_hold_leaves_no_folder(self):
        self.assertEqual(({}, []), self._holding("NO_SUCH_ASSET"),
                         "an empty hold left its temp folder behind")

    def test_a_failed_copy_takes_the_folder_with_it(self):
        def refused(source, target):
            raise OSError("disk full")

        answer, left = self._holding(self.mat_id, refused)
        self.assertEqual((OSError, []), (type(answer), left),
                         "a failed copy left its temp folder behind, or did not raise OSError")


class SwitchRollsBackOnALedgerRefusal(_Case):
    """Ledger and base files are written as one change: a failed ledger write changes nothing."""

    def test_the_base_returns_when_the_ledger_will_not_write(self):
        versions.create_version(self.prefs, self.mat_id)          # V1
        self._rewrite_base(b"EDITED-STATE")
        versions.create_version(self.prefs, self.mat_id)          # V2
        with test_support.full_disk_for(versions._ledger_path(self.prefs, self.mat_id)):
            self.assertFalse(
                versions.switch_active(self.prefs, self.mat_id, 1))
        self.assertEqual(
            b"EDITED-STATE", self._base_bytes(),
            "the base holds version 1 while the ledger still names "
            "version 2 - the promotion was not rolled back")
        self.assertEqual(
            2, versions.active_version(self.prefs, self.mat_id),
            "the ledger changed although its write failed")


class ASwitchPutsTheWholeVersionOnTheBase(_Case):
    """A version saved without a builder or a render removes the other version's from the base."""

    def setUp(self):
        super().setUp()
        self.builder = self.base_record
        self.png = self.base_png
        for path in (self.builder, self.png):    # version 1: an older save, its render not yet written
            if os.path.exists(path):
                os.remove(path)
        self.assertEqual(1, versions.create_version(self.prefs, self.mat_id))
        self._rewrite_base(b"V2-NETWORK")
        self._set_base_builder("v2")
        with open(self.png, "w", encoding="utf-8") as fh:
            fh.write("V2-RENDER")
        self.assertEqual(2, versions.create_version(self.prefs, self.mat_id))

    def _in_base(self):
        return {"builder": bool(self._base_builder()), ".png": os.path.exists(self.png)}

    def _archived_png(self, number):
        return os.path.exists(os.path.join(versions.versions_dir(self.prefs, self.mat_id),
                                           versions.file_stem(self.mat_id, number) + ".png"))

    def test_a_kind_the_version_lacks_leaves_the_base(self):
        self.assertTrue(versions.switch_active(self.prefs, self.mat_id, 1))
        self.assertEqual({"builder": False, ".png": False}, self._in_base(),
                         "version 2's builder or picture is still in the base beside version 1")
        self.assertTrue(versions.switch_active(self.prefs, self.mat_id, 2))
        self.assertEqual({"builder": True, ".png": True}, self._in_base())
        self.assertEqual("v2", self._base_builder().get("interface"))
        self.assertTrue(versions.switch_active(self.prefs, self.mat_id, 1))
        self.assertEqual([1, 2], [int(r["n"]) for r in versions.list_versions(
            self.prefs, self.mat_id)], "a switch back and forth created a version")

    def test_a_kind_that_will_not_leave_is_finished_once_it_can(self):
        from unittest import mock
        from amaze.core import guard, library_db
        real = guard.Disk.remove

        def held(disk, path):    # the picture held open by a viewer while it is removed
            if os.path.normpath(path) == os.path.normpath(self.png):
                raise PermissionError(13, "Permission denied", path)
            return real(disk, path)

        with mock.patch.object(guard.Disk, "remove", held):
            self.assertTrue(versions.switch_active(self.prefs, self.mat_id, 1),
                            "a recorded switch that waits on one file was reported as failed")
        self.assertTrue(library_db.guard_of(self.prefs).recover(),
                        "the half-applied switch left no journal to finish")
        self.assertEqual({"builder": False, ".png": False}, self._in_base(),
                         "the finished switch left version 2's files beside version 1")
        self.assertEqual(1, versions.active_version(self.prefs, self.mat_id))

    def test_a_switch_through_the_model_records_no_picture(self):
        """Checked twice: the switch removes the picture, the repaint records none (the spy)."""
        from unittest import mock
        from amaze.core import library as library_mod
        model = library_mod.MaterialLibrary(preferences=self.prefs)
        with mock.patch.object(versions, "record_render",
                               wraps=versions.record_render) as recorded:
            self.assertTrue(model.switch_version(
                model.find_asset_row_by_id(self.mat_id), 1))
        self.assertFalse(self._archived_png(1),
                         "version 2's picture was recorded into version 1's archive")
        self.assertFalse(recorded.called, "a switch recorded the base picture as a fresh render")


class AVersionHoldsTheBuilderAndNeverTheMetadata(_Case):
    """`<stem>.json` is the builder alone, so a switch keeps the base's own metadata."""

    def _archive(self, number, suffix):
        return os.path.join(versions.versions_dir(self.prefs, self.mat_id),
                            versions.file_stem(self.mat_id, number) + suffix)

    def _set_metadata(self, name):
        asset_record.write_section(self.base_record, asset_record.METADATA,
                                   {"id": self.mat_id, "name": name})

    def test_an_archive_holds_no_metadata_and_a_metadata_edit_mints_nothing(self):
        self._set_metadata("Before")
        self._set_base_builder("v1")
        self.assertEqual(1, versions.create_version(self.prefs, self.mat_id))
        archived = asset_record.read(self._archive(1, ".json"))
        self.assertEqual({}, archived[asset_record.METADATA], "a version archived the metadata")
        self.assertEqual("v1", archived[asset_record.BUILDER].get("interface"))
        self._set_metadata("Renamed")
        self.assertTrue(versions.keep_base(self.prefs, self.mat_id))
        self.assertEqual(1, versions.version_count(self.prefs, self.mat_id),
                         "a metadata edit made the base differ from its version")

    def test_a_switch_takes_the_builder_and_keeps_the_metadata(self):
        self._set_base_builder("v1")
        versions.create_version(self.prefs, self.mat_id)
        self._set_base_builder("v2")
        versions.create_version(self.prefs, self.mat_id)
        self._set_metadata("Current name")
        self.assertTrue(versions.switch_active(self.prefs, self.mat_id, 1))
        record = asset_record.read(self.base_record)
        self.assertEqual("v1", record[asset_record.BUILDER].get("interface"))
        self.assertEqual("Current name", record[asset_record.METADATA].get("name"),
                         "the switch put an old version's metadata on the base")


class TheBaseModelSwitchesInItsOwnSection(_Case):
    """`switch_version` uses the section its model names, as every other version call does."""

    def test_a_switch_reads_the_section_the_model_names(self):
        from amaze.core import library as library_mod
        model = library_mod.MaterialLibrary(preferences=self.prefs)
        row = model.find_asset_row_by_id(self.mat_id)
        model.VERSION_SECTION = versions.NODE    # its store and its base are both in nodes/
        nodes_dir = material.section_folder(self.prefs.dir, library_files.NODES)
        os.makedirs(nodes_dir, exist_ok=True)
        for path in (self.base_mat, self.base_record):
            os.replace(path, os.path.join(nodes_dir, os.path.basename(path)))
        self.base_mat = material.payload_path(self.prefs, self.mat_id, ".mat",
                                              library_files.NODES)
        original = self._base_bytes()
        versions.create_version(self.prefs, self.mat_id, section=model.VERSION_SECTION)
        self._rewrite_base(b"EDITED-STATE")
        versions.create_version(self.prefs, self.mat_id, section=model.VERSION_SECTION)
        self.assertTrue(model.switch_version(row, 1),
                        "the switch looked for the versions in another section's store")
        self.assertEqual(original, self._base_bytes())
        self.assertEqual("Version 1", model.data(model.index(row, 0), model.ActiveVersionRole),
                         "the row still shows the version it showed before the switch")

    def test_a_rename_shows_on_the_row_at_once(self):
        from amaze.core import library as library_mod
        versions.create_version(self.prefs, self.mat_id)
        model = library_mod.MaterialLibrary(preferences=self.prefs)
        row = model.find_asset_row_by_id(self.mat_id)
        index = model.index(row, 0)
        self.assertEqual("Version 1", model.data(index, model.ActiveVersionRole), "premise")
        self.assertTrue(model.rename_version(row, 1, "Hero look"))
        self.assertEqual("Hero look", model.data(index, model.ActiveVersionRole),
                         "the row kept the old name until something else repainted it")


class TheArchiveIsEachVersionsDurableThumbnail(_Case):
    """record_render copies a fresh PNG into the active slot only, so each version keeps its picture."""

    def _png_paths(self):
        folder = versions.versions_dir(self.prefs, self.mat_id)
        return self.base_png, folder

    def test_a_fresh_render_lands_in_the_active_slot_only(self):
        base, folder = self._png_paths()
        with open(base, "wb") as fh:
            fh.write(b"V1-RENDER")
        versions.create_version(self.prefs, self.mat_id)          # V1
        self._rewrite_base(b"EDITED-STATE")
        versions.create_version(self.prefs, self.mat_id)          # V2
        # Creating V2 copied V1's picture into V2's slot; the new render is written only now.
        with open(base, "wb") as fh:
            fh.write(b"V2-RENDER-FRESH")
        self.assertTrue(versions.record_render(self.prefs, self.mat_id))
        rows = versions.list_versions(self.prefs, self.mat_id)
        stems = {int(r["n"]): versions.file_stem(self.mat_id, r["n"]) for r in rows}
        with open(os.path.join(folder, stems[2] + ".png"), "rb") as fh:
            self.assertEqual(
                b"V2-RENDER-FRESH", fh.read(),
                "the active slot did not take the fresh render - "
                "switching versions can never change the picture")
        with open(os.path.join(folder, stems[1] + ".png"), "rb") as fh:
            self.assertEqual(
                b"V1-RENDER", fh.read(),
                "an INACTIVE slot was touched - a render while V2 is "
                "active must never rewrite V1's picture")

    def test_identical_bytes_cost_no_write(self):
        base, folder = self._png_paths()
        with open(base, "wb") as fh:
            fh.write(b"SAME-PICTURE")
        versions.create_version(self.prefs, self.mat_id)
        stem = versions.file_stem(self.mat_id, 1)
        slot = os.path.join(folder, stem + ".png")
        before = os.stat(slot).st_mtime_ns
        self.assertTrue(versions.record_render(self.prefs, self.mat_id))
        self.assertEqual(
            before, os.stat(slot).st_mtime_ns,
            "identical bytes were rewritten - every switch would rewrite "
            "files in the sync folder")

    def test_no_versions_records_nothing(self):
        base, folder = self._png_paths()
        with open(base, "wb") as fh:
            fh.write(b"PICTURE")
        self.assertFalse(versions.record_render(self.prefs, self.mat_id))
        self.assertFalse(
            os.path.exists(folder),
            "a versions folder appeared for an asset that has no "
            "versions")
        versions.create_version(self.prefs, self.mat_id)
        # The fixture asset ships a render; the case under test is the asset that has none.
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
        model._add_thumb_paths(row)
        stem = versions.file_stem(self.mat_id, 1)
        with open(os.path.join(folder, stem + ".png"), "rb") as fh:
            self.assertEqual(
                b"FRESH-PICTURE", fh.read(),
                "_add_thumb_paths declared the PNG fresh and the "
                "active slot was not updated")


class TheBaseFilesFollowTheLibrarysExtensions(_Case):
    """A library whose shared settings name other file extensions versions the files it holds."""

    def setUp(self):
        super().setUp()
        self.prefs._ext = ".matx"
        self.prefs._img_ext = ".jpg"
        renamed = self.base_mat[:-len(".mat")] + ".matx"
        os.replace(self.base_mat, renamed)
        self.legacy_mat, self.base_mat = self.base_mat, renamed
        images = material.section_folder(self.prefs.dir, MATERIALS)    # the folder of the one picture
        self.base_image = os.path.join(images, self.mat_id + ".jpg")
        with open(self.base_image, "wb") as fh:
            fh.write(b"RENDER-AS-JPEG")

    def _archived(self, kind):
        stem = versions.file_stem(self.mat_id,
                                  versions.list_versions(self.prefs, self.mat_id)[-1]["n"])
        with open(os.path.join(versions.versions_dir(self.prefs, self.mat_id),
                               stem + kind), "rb") as fh:
            return fh.read()

    def test_a_switch_writes_the_payload_under_its_own_extension(self):
        original = self._base_bytes()
        self.assertEqual(1, versions.create_version(self.prefs, self.mat_id))
        self.assertEqual(original, self._archived(".mat"))
        self.assertEqual(b"RENDER-AS-JPEG", self._archived(".png"))
        self._rewrite_base(b"EDITED-STATE")
        versions.create_version(self.prefs, self.mat_id)
        self.assertTrue(versions.switch_active(self.prefs, self.mat_id, 1))
        self.assertEqual(original, self._base_bytes())
        self.assertFalse(os.path.exists(self.legacy_mat),
                         "the switch wrote a payload this library never reads")


class StoreTest(_Case):

    def test_create_archives_the_base_and_becomes_active(self):
        self.assertEqual(0, versions.version_count(self.prefs, self.mat_id))
        self.assertEqual([], versions.list_versions(self.prefs, self.mat_id))
        n = versions.create_version(self.prefs, self.mat_id)
        self.assertEqual(1, n)
        self.assertEqual(1, versions.active_version(self.prefs, self.mat_id))
        row = versions.list_versions(self.prefs, self.mat_id)[0]
        self.assertNotIn("file", row, "the ledger row still names its files")
        archived = os.path.join(
            versions.versions_dir(self.prefs, self.mat_id),
            "%s_1.mat" % self.mat_id)
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
                         "never; the archive is a copy of the base, "
                         "not the source")

    def test_an_unreadable_ledger_blocks_writes_not_reads(self):
        versions.create_version(self.prefs, self.mat_id)
        ledger = os.path.join(
            versions.versions_dir(self.prefs, self.mat_id),
            versions.LEDGER)
        with open(ledger, "w", encoding="utf-8") as fh:
            fh.write("{ broken")
        self.assertEqual(0, versions.version_count(self.prefs, self.mat_id))
        self.assertEqual(0, versions.create_version(self.prefs, self.mat_id),
                         "a create wrote over an unreadable ledger")
        self.assertFalse(versions.switch_active(self.prefs, self.mat_id, 1))

    def test_a_version_saved_with_nobody_picked_is_unsigned(self):
        """With nobody picked a version is saved unsigned, and nobody is made."""
        from amaze.core import users
        self.prefs.library_user = ""
        versions.create_version(self.prefs, self.mat_id)
        row = versions.list_versions(self.prefs, self.mat_id)[0]
        self.assertEqual("", row["author"])
        self.assertEqual({}, users.all_users(self.prefs), "saving a version made a user")


class VersionFilesAreNamedByIdAndNumberTest(_Case):
    """A version's files are `<id>_<n>.*`; the ledger names no file, and names only its rows."""

    def test_the_files_carry_the_id_and_the_number(self):
        from amaze.core import users
        self.prefs.library_user = users.create(self.prefs, "Crimson")
        versions.create_version(self.prefs, self.mat_id)
        row = versions.list_versions(self.prefs, self.mat_id)[0]
        self.assertEqual("Crimson", row.get("author"),
                         "the author was not taken from prefs")
        self.assertNotIn("file", row)
        self.assertEqual("%s_1" % self.mat_id, versions.file_stem(self.mat_id, 1))
        folder = versions.versions_dir(self.prefs, self.mat_id)
        self.assertEqual({"%s_1.mat" % self.mat_id, "%s_1.json" % self.mat_id},
                         {name for name in os.listdir(folder)
                          if name.endswith((".mat", ".json")) and name != versions.LEDGER})

    def test_two_writers_same_number_never_collide(self):
        """Two real user records writing the same version number never collide on disk."""
        from amaze.core import users
        self.prefs.library_user = users.create(self.prefs, "Crimson")
        versions.create_version(self.prefs, self.mat_id)
        ledger_path = os.path.join(
            versions.versions_dir(self.prefs, self.mat_id),
            versions.LEDGER)
        with open(ledger_path, encoding="utf-8") as fh:
            frozen = fh.read()
        self._rewrite_base(b"MACHINE B EDIT")
        self.prefs.library_user = users.create(self.prefs, "Cobalt")
        versions.create_version(self.prefs, self.mat_id)
        with open(ledger_path, "w", encoding="utf-8") as fh:  # a sync's last-write-wins: put A's ledger back
            fh.write(frozen)
        folder = versions.versions_dir(self.prefs, self.mat_id)
        self.assertTrue(
            os.path.exists(os.path.join(folder, "%s_1.mat" % self.mat_id)))
        self.assertTrue(
            os.path.exists(os.path.join(folder, "%s_2.mat" % self.mat_id)),
            "the second writer's file survived the ledger overwrite")

    def test_a_file_the_ledger_does_not_name_is_an_orphaned_file(self):
        """It is no version: never a row, never switched to; Check Library names it orphaned."""
        from amaze.core import repair
        self.prefs.library_user = "Crimson"
        versions.create_version(self.prefs, self.mat_id)
        folder = versions.versions_dir(self.prefs, self.mat_id)
        stray = "%s_2.mat" % self.mat_id
        with open(os.path.join(folder, stray), "wb") as fh:
            fh.write(b"THE OTHER MACHINES VERSION")
        self.assertEqual([1], [int(row["n"]) for row in
                               versions.list_versions(self.prefs, self.mat_id)])
        before = self._base_bytes()
        self.assertFalse(versions.switch_active(self.prefs, self.mat_id, 2))
        self.assertEqual(before, self._base_bytes())
        key = "materials/versions/%s/" % self.mat_id
        self.assertEqual([stray], repair.survey(self.prefs.dir)["unaccounted"].get(key))
        self.assertEqual(3, versions.create_version(self.prefs, self.mat_id),
                         "a new version wrote over the orphaned file")
        with open(os.path.join(folder, stray), "rb") as fh:
            self.assertEqual(b"THE OTHER MACHINES VERSION", fh.read())

    def test_a_file_under_an_older_name_is_not_read(self):
        """`1.mat` is not version 1's file: only `<id>_1.mat` is."""
        self.prefs.library_user = "Crimson"
        versions.create_version(self.prefs, self.mat_id)
        folder = versions.versions_dir(self.prefs, self.mat_id)
        for name in os.listdir(folder):
            if name.startswith(self.mat_id + "_1."):
                os.rename(os.path.join(folder, name),
                          os.path.join(folder, name[len(self.mat_id) + 1:]))
        self._rewrite_base(b"EDITED PAST VERSION ONE")
        self.assertEqual("", versions.version_file(self.prefs, self.mat_id, 1))
        self.assertFalse(
            versions.switch_active(self.prefs, self.mat_id, 1))
        self.assertEqual(b"EDITED PAST VERSION ONE", self._base_bytes())

    def test_one_listdir_seeds_the_tile_caches(self):
        """One listdir at model build answers for unversioned assets; only versioned ones read a ledger."""
        from unittest import mock
        from amaze.core import library as library_mod

        self.prefs.library_user ="Crimson"
        versions.create_version(self.prefs, self.mat_id)
        model = library_mod.MaterialLibrary(preferences=self.prefs)
        asked = []
        real = versions.read_ledger

        def counting(preferences, mat_id, *section):
            asked.append(str(mat_id))
            return real(preferences, mat_id, *section)

        with mock.patch.object(versions, "read_ledger",
                               side_effect=counting):
            for row in range(len(model.assets)):
                index = model.index(row, 0)
                model.data(index, model.VersionsRole)
                model.data(index, model.ActiveVersionRole)
        self.assertLessEqual(
            set(asked), {self.mat_id},
            "an asset with no versions folder read the ledger: %s"
            % sorted(set(asked) - {self.mat_id}))
        self.assertTrue(asked, "the versioned asset must still read "
                        "its ledger - the listdir only covers assets with no versions")


class TheWholeLoopThroughTheModelTest(unittest.TestCase):
    """Parameter-only saves create versions; a switch resets the baseline so Update Existing works."""

    def setUp(self):
        from amaze.core import library as library_mod
        from amaze.core import renderers
        from amaze.render import nodes as nodes_mod
        self.nodes = nodes_mod
        self.renderers = renderers
        test_support.pin_env(self, "OCIO", "/dev/null")    # save_node gates on $OCIO; nothing renders here
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
                    if self.renderers.is_karma(
                        self.model.assets[r].renderer))

    def test_parameter_only_update_creates_versions(self):
        # A real parameter-only edit: import, tweak one float, update.
        row = self._karma_row()
        mat = self.model.assets[row]
        ok, reason, _created = material_actions.import_asset_to_scene(self.model,
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

        renderer = material_actions.update_asset_content(self.model, row, imported)
        self.assertTrue(renderer, "premise: the update itself succeeded")

        from amaze.core import versions as versions_mod
        count = versions_mod.version_count(self.prefs, mat.mat_id)
        self.assertEqual(2, count,
                         "a parameter-only update did not produce the "
                         "pre-edit version and the new one (got %d)"
                         % count)
        self.assertEqual(count, self.model.data(
            self.model.index(row, 0), self.model.VersionsRole),
            "`VersionsRole` differs from the version count")

        base = self.model.asset_files(mat.mat_id)["mat"]
        with open(base, "rb") as fh:
            edited = fh.read()

        self.assertTrue(self.model.switch_version(row, 1))
        with open(base, "rb") as fh:
            self.assertNotEqual(edited, fh.read(),
                                "switching to Version 1 left the edited "
                                "bytes on the base")

        known = self.model._content_state.get(str(mat.mat_id))
        current = self.model._content_stat(mat.mat_id)
        self.assertEqual(known, current,
                         "switch_version did not reset the baseline - the next "
                         "Update Existing will be refused as a conflict")

    def test_a_structural_update_does_not_version(self):
        row = self._karma_row()
        mat = self.model.assets[row]
        fresh = self._build(self.staging, "structural_probe")
        renderer = material_actions.update_asset_content(self.model, row, fresh)
        self.assertTrue(renderer, "premise: the update succeeded")
        from amaze.core import versions as versions_mod
        self.assertEqual(0, versions_mod.version_count(
            self.prefs, mat.mat_id),
            "a structural update created versions - archiving a "
            "different structure under the same history is the error the "
            "signature exists to prevent")


class DeletingAUser(unittest.TestCase):
    """Deleting a user removes the record and their tagged favourites and folders, and only theirs."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)

    def _become(self, uid):
        self.prefs.library_user = uid

    def test_delete_removes_the_record_and_touches_nobody_elses_rows(self):
        from amaze.core import library_db, locations, users
        anna = users.create(self.prefs, "Anna")
        bo = users.create(self.prefs, "Bo")
        self._become(anna)
        self.assertTrue(locations.set_favourite(self.prefs, "m-anna", True))
        self._become(bo)
        self.assertTrue(locations.set_favourite(self.prefs, "m-bo", True))

        self.assertTrue(users.delete(self.prefs, anna))

        self.assertEqual({bo: "Bo"}, users.all_users(self.prefs))
        stars = library_db.document(self.prefs, library_files.FILES).everyones(locations.FAVORITES)
        self.assertTrue(stars.get(bo), "the deletion removed the other user's stars: %s" % stars)
        self.assertTrue(stars.get(anna), "the deletion rewrote another user's rows: %s" % stars)
        self.assertTrue(locations.is_favourite(self.prefs, "m-bo"))
        self.assertFalse(locations.is_favourite(self.prefs, "m-anna"),
                         "the deleted user's star shows for the remaining user")
        self.assertFalse(users.delete(self.prefs, "f" * 32),
                         "deleting an unknown user returned True")

    def test_deleting_yourself_clears_this_machines_pointer(self):
        from amaze.core import users
        anna = users.create(self.prefs, "Anna")
        users.create(self.prefs, "Bo")
        self._become(anna)
        self.assertTrue(users.delete(self.prefs, anna))
        self.assertEqual("", str(self.prefs.library_user or ""),
                         "the pointer still names the deleted user")
        self.assertIsNone(users.current(self.prefs),
                          "a user was picked silently - the ASK "
                          "state is for the picker to resolve")

    def test_the_last_deletion_leaves_nobody_and_a_stale_pointer_makes_nobody(self):
        from amaze.core import users
        only = users.create(self.prefs, "Anna")
        self._become(only)
        self.assertTrue(users.delete(self.prefs, only))
        self.assertEqual(users.MINT, users.first_run_state(self.prefs))

        self._become(only)    # another machine still pointing at the deleted UID
        self.assertIsNone(users.current(self.prefs))
        self.assertEqual({}, users.all_users(self.prefs), "a stale pointer made a user")


if __name__ == "__main__":
    unittest.main(verbosity=2)
