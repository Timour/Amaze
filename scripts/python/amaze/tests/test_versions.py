"""The version store: the base files stay the truth, the archive is a copy of it, and losing versions/ entirely costs nothing but history."""

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
    """The first Update on an asset archives the PRE-EDIT state as Version 1, from a held-aside copy of the asset's files, keyed by `versions.SOURCE_KINDS` and never by filename suffix."""

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
    """switch_active promotes the archive over the base and THEN writes the ledger, so a refused ledger write must roll the promotion back rather than leave the base holding a version the ledger does not name."""

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
        self.assertEqual(
            2, versions.active_version(self.prefs, self.mat_id),
            "the ledger moved despite the refusal")


class TheArchiveIsEachVersionsDurableThumbnail(_Case):
    """A version is minted at SAVE time, before that save's render lands, so a fresh archive slot starts holding the previous version's picture; record_render runs wherever a row's PNG is declared fresh and copies it into the ACTIVE slot, so each version keeps its own picture until the version goes."""

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
        # The mint archived V1's picture into V2's slot; the replacing render lands only now.
        with open(base, "wb") as fh:
            fh.write(b"V2-RENDER-FRESH")
        self.assertTrue(versions.record_render(self.prefs, self.mat_id))
        rows = versions.list_versions(self.prefs, self.mat_id)
        stems = {int(r["n"]): r["file"] for r in rows}
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
        stem = versions.list_versions(self.prefs, self.mat_id)[0]["file"]
        slot = os.path.join(folder, stem + ".png")
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
        stem = versions.list_versions(self.prefs, self.mat_id)[0]["file"]
        with open(os.path.join(folder, stem + ".png"), "rb") as fh:
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
        stem = versions.list_versions(self.prefs, self.mat_id)[0]["file"]
        archived = os.path.join(
            versions.versions_dir(self.prefs, self.mat_id),
            stem + ".mat")
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
        self.prefs.library_user ="Chosen"
        versions.create_version(self.prefs, self.mat_id)
        self.assertEqual("Chosen", versions.list_versions(
            self.prefs, self.mat_id)[0]["author"])

    def test_no_user_mints_one_on_a_colour_name_never_harvested(self):
        """A library with nobody in it mints its first user once per LIBRARY from the colour pool and signs with that name - never the OS user, never the machine name - and resolves it ONCE, not per save."""
        import getpass
        import platform
        from amaze.core import users
        self.prefs.library_user = ""  # NOBODY, said out loud: the mint only runs on an empty pointer, and the shared fixture carries one so tagged stores can key at all
        versions.create_version(self.prefs, self.mat_id)
        author = versions.list_versions(self.prefs, self.mat_id)[0]["author"]
        self.assertIn(author, users.PLACEHOLDER_NAMES)
        self.assertEqual(author,
                         users.name_for(self.prefs, self.prefs.library_user),
                         "prefs must point at the UID whose name signed")
        for harvested in (getpass.getuser(), platform.node(),
                          os.environ.get("USER", "")):
            if harvested:
                self.assertNotEqual(harvested.lower(), author.lower())
        self._rewrite_base(b"EDITED")
        versions.create_version(self.prefs, self.mat_id)
        second = versions.list_versions(self.prefs, self.mat_id)[1]["author"]
        self.assertEqual(author, second,
                         "the identity is resolved ONCE, not per save")


class VersionFilesCarryTheirWriterTest(_Case):
    """The archive stem is <writer>-<n>, the writer is `library_user`, and the ledger row records the stem it wrote; what keeps two writers apart is stepping past a stem already on disk."""

    def test_the_stem_carries_the_writer(self):
        self.prefs.library_user ="Crimson"
        versions.create_version(self.prefs, self.mat_id)
        row = versions.list_versions(self.prefs, self.mat_id)[0]
        self.assertEqual("Crimson-1", row.get("file"))
        folder = versions.versions_dir(self.prefs, self.mat_id)
        self.assertTrue(
            os.path.exists(os.path.join(folder, "Crimson-1.mat")))

    def test_two_writers_same_number_never_collide(self):
        """TWO DIFFERENT PEOPLE, which under the UID scheme means two real user records - the second writer is not a machine that retyped a name, it is somebody the library knows about."""
        from amaze.core import users
        self.prefs.library_user ="Crimson"
        versions.create_version(self.prefs, self.mat_id)
        ledger_path = os.path.join(
            versions.versions_dir(self.prefs, self.mat_id),
            versions.LEDGER)
        with open(ledger_path, encoding="utf-8") as fh:
            frozen = fh.read()
        self._rewrite_base(b"MACHINE B EDIT")
        self.prefs.library_user = users.create(self.prefs, "Cobalt")
        versions.create_version(self.prefs, self.mat_id)
        with open(ledger_path, "w", encoding="utf-8") as fh:  # the other machine never saw B's ledger write: put A's back, exactly what a sync's last-write-wins does
            fh.write(frozen)
        folder = versions.versions_dir(self.prefs, self.mat_id)
        self.assertTrue(
            os.path.exists(os.path.join(folder, "Crimson-1.mat")))
        self.assertTrue(
            os.path.exists(os.path.join(folder, "Cobalt-2.mat")),
            "the second writer's file survived the ledger overwrite")

    def test_a_stray_archive_is_adopted_on_read(self):
        """The sync-survival half: a version file the ledger does not know - the row lost to last-write-wins - comes back as a row on the next read, writer parsed from its stem."""
        self.prefs.library_user ="Crimson"
        versions.create_version(self.prefs, self.mat_id)
        folder = versions.versions_dir(self.prefs, self.mat_id)
        with open(os.path.join(folder, "Cobalt-2.mat"), "wb") as fh:
            fh.write(b"THE OTHER MACHINES VERSION")
        rows = versions.list_versions(self.prefs, self.mat_id)
        self.assertEqual(2, len(rows))
        adopted = rows[-1]
        self.assertEqual("Cobalt-2", adopted.get("file"))
        self.assertEqual("Cobalt", adopted.get("author"))
        self.assertTrue(
            versions.switch_active(self.prefs, self.mat_id,
                                   int(adopted["n"])),
            "an adopted version must be switchable")
        self.assertEqual(b"THE OTHER MACHINES VERSION",
                         self._base_bytes())

    def test_legacy_bare_numbers_still_switch(self):
        """The shape every pre-signing library holds today - 1.mat, 2.mat, rows with no stem - which readers accept forever."""
        self.prefs.library_user ="Crimson"
        versions.create_version(self.prefs, self.mat_id)
        folder = versions.versions_dir(self.prefs, self.mat_id)
        row = versions.list_versions(self.prefs, self.mat_id)[0]
        legacy = os.path.join(folder, "1.mat")
        os.rename(os.path.join(folder, "%s.mat" % row["file"]), legacy)
        for kind in (".interface", ".builder.json", ".png"):
            source = os.path.join(folder, "%s%s" % (row["file"], kind))
            if os.path.exists(source):
                os.rename(source,
                          os.path.join(folder, "1%s" % kind))
        ledger_path = os.path.join(folder, versions.LEDGER)
        with open(ledger_path, encoding="utf-8") as fh:
            ledger = json.load(fh)
        for entry in ledger["versions"]:
            entry.pop("file", None)
        with open(ledger_path, "w", encoding="utf-8") as fh:
            json.dump(ledger, fh)
        self._rewrite_base(b"EDITED PAST VERSION ONE")
        self.assertTrue(
            versions.switch_active(self.prefs, self.mat_id, 1))
        self.assertNotEqual(b"EDITED PAST VERSION ONE",
                            self._base_bytes())

    def test_one_listdir_seeds_the_tile_caches(self):
        """One listdir at model build answers for every asset WITHOUT a versions folder - the overwhelming case - so asking both version roles across the whole model reads the ledger only for assets that really have one."""
        from unittest import mock
        from amaze.core import library as library_mod

        self.prefs.library_user ="Crimson"
        versions.create_version(self.prefs, self.mat_id)
        model = library_mod.MaterialLibrary(preferences=self.prefs)
        asked = []
        real = versions.read_ledger

        def counting(preferences, mat_id):
            asked.append(str(mat_id))
            return real(preferences, mat_id)

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
                        "its ledger - the seed only answers absence")

    def test_the_ledger_has_a_snapshot_tier(self):
        """versions.json was the one store without one."""
        self.prefs.library_user ="Crimson"
        versions.create_version(self.prefs, self.mat_id)
        self._rewrite_base(b"EDITED")
        versions.create_version(self.prefs, self.mat_id)
        folder = versions.versions_dir(self.prefs, self.mat_id)
        traces = [name for name in os.listdir(folder)
                  if name.startswith(versions.LEDGER + ".bak")]
        self.assertTrue(traces, "no snapshot beside versions.json")


class TheWholeLoopThroughTheModelTest(unittest.TestCase):
    """Parameter-only save -> versions appear; switch -> the base holds the old bytes and the next Update Existing is not refused; the badge role counts."""

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
        # A REAL parameter-only edit - import, tweak one float, update; a fresh network would be structural.
        row = self._karma_row()
        mat = self.model.assets[row]
        ok, reason, _created = self.model.import_asset_to_scene(
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

        # THE GUARD MUST READ OUR OWN SWITCH AS OURS - without the baseline refresh inside switch_version the next update reads the switch as another session's write and refuses.
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


class DeletingAUser(unittest.TestCase):
    """Deleting a user removes the record AND everything tagged theirs - favourites and registered folders - and only theirs (settled 2026-08-22: sweep, blank pointer on self-delete, last-user deletion allowed)."""

    def setUp(self):
        self.prefs = test_support.fixture_prefs(self)

    def _become(self, uid):
        self.prefs.library_user = uid

    def test_delete_sweeps_only_their_tagged_rows(self):
        from amaze.core import keyed_store, locations, users
        anna = users.create(self.prefs, "Anna")
        bo = users.create(self.prefs, "Bo")
        self._become(anna)
        self.assertTrue(locations.set_favourite(self.prefs, "m-anna", True))
        self.assertTrue(locations.register(
            self.prefs, os.path.join(self.prefs.dir, "anna-folder")))
        self._become(bo)
        self.assertTrue(locations.set_favourite(self.prefs, "m-bo", True))

        self.assertTrue(users.delete(self.prefs, anna))

        self.assertEqual({bo: "Bo"}, users.all_users(self.prefs))
        favs = keyed_store.open_store(
            locations.FAVOURITES_SPEC, self.prefs).everyones()
        owners = {keyed_store.untagged_key(
            locations.FAVOURITES_SPEC, key)[0] for key in favs}
        self.assertEqual({bo}, owners,
                         "the sweep left the deleted user's stars, or "
                         "took the survivor's: %s" % favs)
        records = keyed_store.open_store(
            locations.SPEC, self.prefs).everyones()
        owners = {keyed_store.untagged_key(
            locations.SPEC, key)[0] for key in records}
        self.assertNotIn(anna, owners,
                         "the deleted user's registered folder survived")

    def test_delete_answers_False_for_a_stranger(self):
        from amaze.core import users
        users.create(self.prefs, "Anna")
        self.assertFalse(users.delete(self.prefs, "f" * 32))

    def test_deleting_yourself_clears_this_machines_pointer(self):
        from amaze.core import users
        anna = users.create(self.prefs, "Anna")
        users.create(self.prefs, "Bo")
        self._become(anna)
        self.assertTrue(users.delete(self.prefs, anna))
        self.assertEqual("", str(self.prefs.library_user or ""),
                         "the pointer still names the deleted user")
        self.assertIsNone(users.current(self.prefs),
                          "somebody was adopted silently - the ASK "
                          "state is the picker's to resolve")

    def test_the_last_deletion_returns_to_mint_and_a_stale_pointer_is_not_a_name(self):
        from amaze.core import users
        only = users.create(self.prefs, "Anna")
        self._become(only)
        self.assertTrue(users.delete(self.prefs, only))
        self.assertEqual(users.MINT, users.first_run_state(self.prefs))

        self._become(only)    # another machine still pointing at the dead UID
        minted = users.current(self.prefs)
        self.assertTrue(minted)
        name = users.name_for(self.prefs, minted)
        self.assertIn(name, users.PLACEHOLDER_NAMES,
                      "the stale UID hex was minted as a NAME: %r"
                      % name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
