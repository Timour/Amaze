"""Versions: one test per requirement in docs/requirements/versions.md."""

import os
import shutil
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")    # the first app picks the platform ▸p/first-app-picks-the-platform
from PySide6 import QtCore, QtWidgets  # noqa: E402
import hou  # noqa: E402

from amaze import messages
from amaze.actions import materials as material_actions
from amaze.core import asset_files, asset_record, guard, library, library_db, library_files
from amaze.core import library_settings, notes, versions
from amaze.dialogs import versions_window
from amaze.pane import assets
from amaze.tests import faults, test_support

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

MATERIALS = library_files.MATERIALS
GOLD, GLASS = "139888336889814930", "139888337058723210"    # two fixture materials
FIXED_DATE = types.SimpleNamespace(strftime=lambda *_args: "2026-11-24 10:00")


def read(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


class StoreTest(unittest.TestCase):
    """A fixture library whose material GOLD has version 1 and version 2, two networks apart."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        patch = mock.patch.object(versions, "time", FIXED_DATE)    # a ledger row's date
        patch.start()
        self.addCleanup(patch.stop)
        self.prefs = self.library()

    def library(self):
        prefs = test_support.fixture_prefs(self)
        self.files = asset_files.asset_files_for(prefs, GOLD, MATERIALS)
        for number in (1, 2):
            self.network(b"network %d" % number, "builder %d" % number)
            self.assertEqual(number, versions.create_version(prefs, GOLD))
        return prefs

    def network(self, data: bytes, builder: str) -> None:
        """The material's network and builder on disk replaced, as a save over it writes them."""
        with open(self.files["mat"], "wb") as handle:
            handle.write(data)
        test_support.write_section(self.files["json"], asset_record.BUILDER,
                                   {"type": "subnet", "interface": builder, "values": {}})

    def archive(self, number: int, suffix: str) -> str:
        return os.path.join(versions.versions_dir(self.prefs, GOLD),
                            versions.file_stem(GOLD, number) + suffix)

    def ledger(self) -> str:
        return os.path.join(versions.versions_dir(self.prefs, GOLD), library_files.LEDGER)

    def builder(self, path: str) -> str:
        return asset_record.read(path)[asset_record.BUILDER].get("interface")

    def kept(self) -> dict:
        return {path: data for path, data in test_support.library_state(self.prefs.dir).items()
                if "/versions/" in path}

    def test_vs01_a_switch_keeps_what_no_version_holds_or_does_not_switch(self):
        self.network(b"edited", "edited")
        before = test_support.library_state(self.prefs.dir)
        with test_support.full_disk_for(self.ledger()):
            self.assertFalse(versions.switch_active(self.prefs, GOLD, 1))
        self.assertEqual(before, test_support.library_state(self.prefs.dir))
        self.assertTrue(versions.switch_active(self.prefs, GOLD, 1))
        self.assertEqual((b"network 1", b"edited", "edited"), (
            read(self.files["mat"]), read(self.archive(3, ".mat")),
            self.builder(self.archive(3, ".json"))))

    def cut(self, act, disk) -> dict:
        """A new library's state after `act` ran on `disk` and the library was opened again."""
        self.prefs = self.library()
        library_db.guard_of(self.prefs).disk = disk
        try:
            act(self.prefs)
        except faults.Cut:
            pass
        faults.crash(self.prefs)
        return test_support.library_state(self.prefs.dir)

    def test_vs02_making_or_switching_a_version_is_applied_whole_or_not_at_all(self):
        for name, act in (("make", lambda prefs: versions.create_version(prefs, GOLD)),
                          ("switch", lambda prefs: versions.switch_active(prefs, GOLD, 1))):
            before = test_support.library_state(self.library().dir)
            counting = faults.FaultDisk()
            after = self.cut(act, counting)
            self.assertNotEqual(before, after, name)
            for torn in (False, True):
                for step in range(1, counting.steps + 1):
                    found = self.cut(act, faults.FaultDisk(cut_at=step, torn=torn))
                    self.assertIn(found, (before, after), "%s cut at step %d" % (name, step))
            for full_from in (1, 2, 3):
                self.assertEqual(before, self.cut(act, faults.FaultDisk(full_from=full_from)))
        self.prefs = self.library()
        held = faults.FaultDisk(busy=os.path.basename(self.files["mat"]))
        library_db.guard_of(self.prefs).disk = held
        self.assertTrue(versions.switch_active(self.prefs, GOLD, 1), "kept, waiting on the file")
        self.assertEqual((2, b"network 2"), (versions.active_version(self.prefs, GOLD),
                                             read(self.files["mat"])))
        held.free = True
        library_db.guard_of(self.prefs).recover()
        self.assertEqual(after, test_support.library_state(self.prefs.dir))

    def test_vs03_a_new_version_never_writes_over_a_version_file_on_disk(self):
        stray = self.archive(3, ".mat")
        with open(stray, "wb") as handle:
            handle.write(b"another computer's version 3")
        self.assertEqual(4, versions.create_version(self.prefs, GOLD))
        self.assertEqual(b"another computer's version 3", read(stray))
        self.assertEqual([1, 2, 4], [row["n"] for row in versions.list_versions(self.prefs, GOLD)])

    def test_vs04_a_version_list_that_cannot_be_read_is_never_written_over(self):
        with open(self.ledger(), "wb") as handle:
            handle.write(b'{"active": 2, "versions": [')
        before = self.kept()
        self.network(b"edited", "edited")
        self.assertEqual(0, versions.create_version(self.prefs, GOLD))
        self.assertFalse(versions.keep_base(self.prefs, GOLD))
        self.assertFalse(versions.switch_active(self.prefs, GOLD, 1))
        self.assertFalse(versions.rename_version(self.prefs, GOLD, 1, "Hero"))
        self.assertFalse(versions.delete_version(self.prefs, GOLD, 1))
        self.assertEqual(before, self.kept())

    def test_vs05_losing_the_versions_never_touches_the_material(self):
        files = asset_files.asset_files_for(self.prefs, GLASS, MATERIALS)
        own = {kind: read(path) for kind, path in files.items() if os.path.exists(path)}
        self.assertEqual(1, versions.create_version(self.prefs, GLASS))
        os.remove(os.path.join(versions.versions_dir(self.prefs, GLASS), library_files.LEDGER))
        self.assertEqual((0, ""), (versions.version_count(self.prefs, GLASS),
                                   versions.active_version_name(self.prefs, GLASS)))
        shutil.rmtree(versions.versions_dir(self.prefs, GLASS))
        self.assertEqual(own, {kind: read(path) for kind, path in files.items()
                               if os.path.exists(path)})
        model = library.MaterialLibrary(preferences=self.prefs)
        ok, reason, created = material_actions.import_asset_to_scene(
            model, model.index(model.find_asset_row_by_id(GLASS), 0), target="mat")
        for node in created:
            self.addCleanup(test_support.drop_node, node)
        self.assertTrue(ok, reason)

    def test_vs06_deleting_a_version_takes_its_files_and_line_and_nothing_else(self):
        ledger = os.path.relpath(self.ledger(), self.prefs.dir).replace(os.sep, "/")
        before = test_support.library_state(self.prefs.dir)
        gone = {path for path in before if "/%s." % versions.file_stem(GOLD, 1) in path}
        self.assertEqual(3, len(gone), "premise: version 1 has its network, builder and picture")
        self.assertTrue(versions.delete_version(self.prefs, GOLD, 1))
        after = test_support.library_state(self.prefs.dir)
        trashed = {path for path in after if path.startswith(guard.TRASH_DIR + "/")}
        self.assertEqual([2], [row["n"] for row in versions.list_versions(self.prefs, GOLD)])
        self.assertEqual({path: data for path, data in before.items() if path not in gone | {ledger}},
                         {path: data for path, data in after.items()
                          if path not in trashed | {ledger}})
        self.assertEqual(sorted(before[path] for path in gone),
                         sorted(after[path] for path in trashed))

    def listed_in_place(self) -> bool:
        """Whether every version the list names has all of its files in its folder."""
        return all(os.path.exists(self.archive(row["n"], suffix))
                   for row in versions.list_versions(self.prefs, GOLD)
                   for suffix in library_files.VERSION_SUFFIXES)

    def test_vs07_deleting_a_version_is_applied_whole_or_not_at_all(self):
        def act(prefs):
            return versions.delete_version(prefs, GOLD, 1)
        before = test_support.library_state(self.library().dir)
        counting = faults.FaultDisk()
        after = self.cut(act, counting)
        self.assertNotEqual(before, after)
        for torn in (False, True):
            for step in range(1, counting.steps + 1):
                found = self.cut(act, faults.FaultDisk(cut_at=step, torn=torn))
                self.assertIn(found, (before, after), "cut at step %d" % step)
                self.assertTrue(self.listed_in_place(), "cut at step %d" % step)
        for full_from in range(1, counting.writes + 1):    # the disk full from each write on
            self.assertEqual(before, self.cut(act, faults.FaultDisk(full_from=full_from)))
            self.assertTrue(self.listed_in_place())
        for busy in [versions.file_stem(GOLD, 1) + suffix
                     for suffix in library_files.VERSION_SUFFIXES] + [library_files.LEDGER]:
            self.prefs = self.library()
            held = faults.FaultDisk(busy=busy)
            library_db.guard_of(self.prefs).disk = held
            self.assertTrue(act(self.prefs), "kept, waiting on %s" % busy)
            held.free = True
            library_db.guard_of(self.prefs).recover()
            self.assertEqual(after, test_support.library_state(self.prefs.dir), busy)
            self.assertTrue(self.listed_in_place(), "%s held" % busy)

    def test_vs11_a_switch_keeps_the_materials_name_category_tags_and_comments(self):
        held = library_db.document(self.prefs, MATERIALS)
        held.edit("assets", GOLD, name="Current", categories=["Metal"], tags=["shiny"])
        self.assertTrue(library_db.save(self.prefs, MATERIALS))
        key = notes.note_key("material", GOLD)
        self.assertTrue(notes.set_note(self.prefs, key, [{"t": "text", "text": "keep me"}]))
        self.files = asset_files.asset_files_for(self.prefs, GOLD, MATERIALS)    # renamed with it
        row, metadata = held.get("assets", GOLD), asset_record.read(self.files["json"])["metadata"]
        self.assertEqual("Current", metadata.get("name"))
        self.assertTrue(versions.switch_active(self.prefs, GOLD, 1))
        test_support.reset_database_singletons()
        self.assertEqual(("builder 1", metadata), (self.builder(self.files["json"]),
                                                   asset_record.read(self.files["json"])["metadata"]))
        self.assertEqual(row, library_db.document(self.prefs, MATERIALS).get("assets", GOLD))
        self.assertEqual("keep me", notes.note_for(self.prefs, key)["items"][0]["text"])

    def test_vs12_deleting_the_version_in_use_first_selects_the_newest_left(self):
        model = library.MaterialLibrary(preferences=self.prefs)
        row = model.find_asset_row_by_id(GOLD)
        network = read(self.archive(1, ".mat"))
        os.remove(self.archive(1, ".mat"))    # version 1 cannot be put on the material
        before = test_support.library_state(self.prefs.dir)
        self.assertFalse(model.delete_version(row, 2))
        self.assertEqual(before, test_support.library_state(self.prefs.dir))
        with open(self.archive(1, ".mat"), "wb") as handle:
            handle.write(network)
        with mock.patch.object(model, "switch_version", wraps=model.switch_version) as select:
            self.assertTrue(model.delete_version(row, 2))
        select.assert_called_once_with(row, 1)
        self.assertEqual((b"network 1", [1], 1), (
            read(self.files["mat"]), [entry["n"] for entry in versions.list_versions(self.prefs, GOLD)],
            versions.active_version(self.prefs, GOLD)))

    def test_vs20_select_puts_the_whole_version_on_the_material(self):
        os.remove(self.files["thumbnail"])
        self.network(b"network 3", "builder 3")
        self.assertEqual(3, versions.create_version(self.prefs, GOLD))
        model = library.MaterialLibrary(preferences=self.prefs)
        self.assertTrue(model.switch_version(model.find_asset_row_by_id(GOLD), 2))
        self.assertEqual((b"network 2", "builder 2", read(self.archive(2, ".png"))), (
            read(self.files["mat"]), self.builder(self.files["json"]),
            read(self.files["thumbnail"])))
        self.assertTrue(model.switch_version(model.find_asset_row_by_id(GOLD), 3))
        self.assertEqual((b"network 3", "builder 3", False), (
            read(self.files["mat"]), self.builder(self.files["json"]),
            os.path.exists(self.files["thumbnail"])))

    def test_vs21_a_metadata_change_makes_no_version(self):
        library_db.document(self.prefs, MATERIALS).edit(
            "assets", GOLD, name="Renamed", categories=["Wood"], tags=["new"])
        self.assertTrue(library_db.save(self.prefs, MATERIALS))
        self.assertTrue(notes.set_note(self.prefs, notes.note_key("material", GOLD),
                                       [{"t": "text", "text": "a comment"}]))
        self.files = asset_files.asset_files_for(self.prefs, GOLD, MATERIALS)    # renamed with it
        self.assertEqual("Renamed", asset_record.read(self.files["json"])["metadata"]["name"])
        self.assertTrue(versions.keep_base(self.prefs, GOLD))
        self.assertEqual(2, versions.version_count(self.prefs, GOLD))

    def test_vs22_a_render_goes_into_the_active_version_while_it_holds_the_material(self):
        self.assertTrue(versions.switch_active(self.prefs, GOLD, 1))
        other = read(self.archive(2, ".png"))
        with open(self.files["thumbnail"], "wb") as handle:
            handle.write(b"a fresh render")
        self.assertTrue(versions.record_render(self.prefs, GOLD))
        self.assertEqual((b"a fresh render", other),
                         (read(self.archive(1, ".png")), read(self.archive(2, ".png"))))
        self.network(b"saved over with Versions off", "off")
        with open(self.files["thumbnail"], "wb") as handle:
            handle.write(b"its render")
        self.assertFalse(versions.record_render(self.prefs, GOLD))
        self.assertEqual(b"a fresh render", read(self.archive(1, ".png")))

    def delete_answered(self, model, number: int, answer: int) -> tuple:
        """(the questions asked, the question the window shows next) for Delete on `number`."""
        asked = []

        def message(text, **how):
            asked.append((text, how["help"], how["buttons"]))
            return answer
        with mock.patch.object(hou, "ui", types.SimpleNamespace(displayMessage=message),
                               create=True):
            shown = assets.Assets(None).delete_version(model, model.find_asset_row_by_id(GOLD),
                                                       number)
        return asked, shown

    def test_vs28_delete_asks_first_and_names_the_version(self):
        model = library.MaterialLibrary(preferences=self.prefs)
        self.assertTrue(model.rename_version(model.find_asset_row_by_id(GOLD), 1, "Hero"))
        asked, shown = self.delete_answered(model, 1, 1)
        self.assertEqual([(messages.VERSION_DELETE_CONFIRM % "Hero",
                           messages.HELP_DELETE_VERSION % guard.TRASH_DAYS,
                           messages.BUTTONS_DELETE)], asked)
        self.assertEqual([1, 2], [entry["n"] for entry in shown["listed"]])
        self.assertEqual([1, 2], [row["n"] for row in versions.list_versions(self.prefs, GOLD)])

    def test_vs29_after_a_delete_the_versions_left_are_listed_and_no_number_is_given_again(self):
        self.assertEqual(3, versions.create_version(self.prefs, GOLD))
        model = library.MaterialLibrary(preferences=self.prefs)
        state = versions_window.VersionsState(question={
            "listed": versions.list_versions(self.prefs, GOLD), "active": 3})
        self.addCleanup(state.deleteLater)
        changes = []
        state.rows.rowsRemoved.connect(lambda _parent, first, last: changes.append(("-", first, last)))
        state.rows.rowsInserted.connect(lambda _parent, first, last: changes.append(("+", first, last)))
        _asked, shown = self.delete_answered(model, 3, 0)
        state.reasked(shown)
        self.assertEqual((["Version 2", "Version 1"], 2, [("-", 0, 0)]), (
            [row["name"] for row in state.rows.rows], state.picked, changes))
        self.assertEqual(4, versions.create_version(self.prefs, GOLD), "deleted version 3's number")

    def test_vs30_delete_is_off_while_one_version_is_left(self):
        listed = versions.list_versions(self.prefs, GOLD)
        state = versions_window.VersionsState(question={"listed": listed, "active": 2})
        self.addCleanup(state.deleteLater)
        self.assertTrue(state.deletable)
        state.reasked({"listed": listed[1:], "active": 2})
        self.assertFalse(state.deletable)

    def said_on_a_full_disk(self, act) -> list:
        """The messages shown by `act(the pane's assets, the model, GOLD's row)` once the disk is full."""
        model = library.MaterialLibrary(preferences=self.prefs)
        row = model.find_asset_row_by_id(GOLD)
        self.assertTrue(model.rename_version(row, 1, "Hero"))
        said = []

        def message(text, **_how):
            said.append(text)
            return 0
        with mock.patch.object(hou, "ui", types.SimpleNamespace(displayMessage=message),
                               create=True):
            library_db.guard_of(self.prefs).disk = faults.FaultDisk(full_from=1)
            act(assets.Assets(None), model, row)
        return said

    def test_vs31_a_select_that_could_not_be_done_says_so_and_names_the_version(self):
        said = self.said_on_a_full_disk(lambda pane, model, row: pane.select_version(model, row, 1))
        self.assertEqual([messages.VERSION_NOT_SELECTED % "Hero"], said)
        self.assertEqual(2, versions.active_version(self.prefs, GOLD))

    def test_vs32_a_delete_that_could_not_be_done_says_so_and_lists_the_versions_as_they_are(self):
        shown = []
        said = self.said_on_a_full_disk(
            lambda pane, model, row: shown.append(pane.delete_version(model, row, 1)))
        self.assertEqual([messages.VERSION_DELETE_CONFIRM % "Hero",
                          messages.VERSION_NOT_DELETED % "Hero"], said)
        self.assertEqual(([1, 2], 2), ([entry["n"] for entry in shown[0]["listed"]],
                                       shown[0]["active"]))


class SavedOverTest(unittest.TestCase):
    """GOLD loaded into the scene, changed and saved over, as Update Existing does."""

    def setUp(self):
        test_support.pin_env(self, "OCIO", "/dev/null")    # the save checks it; nothing renders
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.prefs = test_support.fixture_prefs(self)
        self.prefs.render_on_import = 0
        self.model = library.MaterialLibrary(preferences=self.prefs)
        self.row = self.model.find_asset_row_by_id(GOLD)
        ok, reason, created = material_actions.import_asset_to_scene(
            self.model, self.model.index(self.row, 0), target="mat")
        self.assertTrue(ok, reason)
        for node in created:
            self.addCleanup(test_support.drop_node, node)
        self.node = next(node for node in created if node.userData("assetlib_id") == GOLD)
        self.mat = self.model.asset_files(GOLD)["mat"]

    def change(self) -> bytes:
        """A value of the scene node changed; the material's network on disk as it was."""
        parm = next(child.parm("specular_roughness") for child in self.node.allSubChildren()
                    if child.parm("specular_roughness") is not None)
        parm.set(parm.eval() / 2 + 0.25)
        return read(self.mat)

    def save_over(self):
        return material_actions.update_asset_content(self.model, self.row, self.node)

    def count(self) -> tuple:
        return (versions.version_count(self.prefs, GOLD), versions.active_version(self.prefs, GOLD))

    def test_vs10_a_save_over_keeps_the_old_material_as_a_version_or_is_refused(self):
        old = self.change()
        self.assertTrue(self.save_over())
        self.assertEqual((2, 2), self.count())
        self.assertEqual((old, read(self.mat)), (read(versions.version_file(self.prefs, GOLD, 1)),
                                                 read(versions.version_file(self.prefs, GOLD, 2))))
        self.node.createNode("null", "added")
        self.assertTrue(self.save_over())
        self.assertEqual((3, 3), self.count())
        self.assertTrue(library_settings.set_allow_overwrite(self.prefs, False))
        self.change()
        self.assertTrue(self.save_over())
        self.assertTrue(library_settings.set_allow_overwrite(self.prefs, True))
        unkept = self.change()
        with test_support.full_disk_for(os.path.join(
                versions.versions_dir(self.prefs, GOLD), library_files.LEDGER)):
            with self.assertRaises(material_actions.UpdateRefused) as refused:
                self.save_over()
        self.assertEqual(messages.UPDATE_REFUSED_NOT_KEPT, str(refused.exception))
        self.assertEqual((unkept, (3, 3)), (read(self.mat), self.count()))

    def test_vs24_after_a_switch_saving_over_is_not_refused(self):
        self.change()
        self.assertTrue(self.save_over())
        self.assertTrue(self.model.switch_version(self.row, 1))
        self.change()
        self.assertTrue(self.save_over())

    def test_vs26_with_versions_off_a_save_over_makes_no_version(self):
        self.change()
        self.assertTrue(self.save_over())
        kept = {path: data for path, data in test_support.library_state(self.prefs.dir).items()
                if "/versions/" in path}
        self.assertTrue(library_settings.set_allow_overwrite(self.prefs, False))
        old = self.change()
        self.assertTrue(self.save_over())
        self.assertNotEqual(old, read(self.mat))
        self.assertEqual(kept, {path: data for path, data in test_support.library_state(
            self.prefs.dir).items() if "/versions/" in path})


class WindowTest(unittest.TestCase):
    """The Versions window opened from the pane over the fixture library."""

    def test_vs27_a_row_that_is_gone_opens_no_versions_window(self):
        from amaze.dialogs import versions_dialog
        panel = test_support.fixture_panel(self)
        model, opened = panel.pane.material_model, []
        self.assertTrue(model.assets, "premise: the fixture library holds materials")

        def dialog(name, *_args, **_kwargs):
            opened.append(name)
            return mock.Mock(exec=lambda: QtWidgets.QDialog.DialogCode.Rejected)

        with mock.patch.object(versions_dialog, "VersionsDialog", dialog), \
                mock.patch.object(model, "version_list", lambda row: (["v1", "v2"], "v1")):
            panel.pane.assets.open_versions(QtCore.QModelIndex(), panel.pane.material_sorted_model,
                                            model)
        self.assertEqual([], opened, "a row that is gone opened another material's versions")


if __name__ == "__main__":
    unittest.main()
