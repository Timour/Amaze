"""Open and switch library: one test per requirement in docs/requirements/open-and-switch.md."""

import json
import os
import shutil
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import hou  # noqa: E402 - the pane engine is Houdini's: hython runs this module

from amaze import messages  # noqa: E402
from amaze.actions import library as library_actions  # noqa: E402
from amaze.core import (documents, guard, library_db, library_files, model_registry,  # noqa: E402
                        users)
from amaze.dialogs import prefs_window  # noqa: E402
from amaze.prefs import persistence  # noqa: E402
from amaze.prefs import prefs as prefs_mod  # noqa: E402
from amaze.tests import test_support  # noqa: E402

MATERIALS, NODES = library_files.MATERIALS, library_files.NODES
state = test_support.library_state


class _Pane(unittest.TestCase):
    """A pane engine on a fixture library, and a second library to switch to."""

    def setUp(self):
        self.pane = test_support.fixture_pane(self)
        self.first = self.pane.prefs.dir

    def library(self, *names) -> tuple:
        """A copy of the fixture library holding users called `names`: (folder, {name: uid})."""
        folder = test_support.seeded_library(self)
        holder = types.SimpleNamespace(dir=folder, library_user="")
        made = {name: users.create(holder, name, library=folder) for name in names}
        library_db.release(holder)
        return folder, made

    def empty_folder(self) -> str:
        folder = test_support.scratch_dir("amaze_new_library_")
        self.addCleanup(shutil.rmtree, folder, True)
        return test_support.posix_path(folder) + "/"

    def apply(self, folder: str, user: str = "", state_=None) -> bool:
        """Preferences picks `folder` and the user named `user`, then Apply; True once open."""
        holder = types.SimpleNamespace(pane=self.pane)
        return test_support.apply_library(self, holder, folder, user=user, state=state_)

    def switch_settings(self) -> tuple:
        """The library, user and Library list settings.json names now."""
        with open(os.path.join(self.pane.prefs.path, "settings.json"), encoding="utf-8") as handle:
            stored = json.load(handle)
        return stored.get("directory"), stored.get("library_user"), stored.get("libraries")

    def rows(self, folder: str, name: str = MATERIALS) -> dict:
        return guard.Guard(folder).read(name).document.get("assets") or {}


class SwitchTest(_Pane):
    """Requirements on what a switch writes, and where."""

    def edit_everything(self) -> None:
        """A rename, a category colour, an icon, a star and a delete, through the models."""
        model, categories = self.pane.material_model, self.pane.category_model
        model.set_tile_name(1, "renamed after the switch")
        categories.set_color(categories._categories[0], "#123456")
        model.set_tile_icon(2, {"face": "generic"})
        model.toggle_fav(3)
        model.remove_rows([4])

    def test_sw01_after_a_switch_every_write_goes_to_the_library_now_open(self):
        model = self.pane.material_model
        self.assertTrue(model.set_tile_name(1, "only in the first library"))
        other, _made = self.library("Sage")
        held = {key: dict(row) for key, row in self.rows(other).items()}
        self.assertTrue(self.apply(other, "Sage"))
        first = state(self.first)
        self.edit_everything()
        library_db.flush()
        self.assertEqual(first, state(self.first), "a write after the switch reached the old one")
        now = self.rows(other)
        self.assertLessEqual(set(now), set(held), "a row of the old library was written here")
        self.assertNotIn("only in the first library", [row.get("name") for row in now.values()])
        self.assertIn("renamed after the switch", [row.get("name") for row in now.values()])
        third, _made = self.library("Sage")
        untouched = state(third)
        self.pane.prefs.dir = third    # the folder named, the models not yet switched
        with test_support.captured_log():
            self.edit_everything()
            library_db.flush()
        self.assertEqual(untouched, state(third), "rows of one library were written into another")

    def test_sw02_a_change_waiting_when_the_library_or_user_switches_keeps_its_place(self):
        other, made = self.library("Sage")
        library_db.set_scheduler(lambda: None)    # the pane's save timer, not yet fired
        anna = self.pane.prefs.library_user
        held = library_db.document(self.pane.prefs, MATERIALS)
        key = sorted(held.table("assets"))[0]
        self.assertTrue(held.put_mine("favorites", key, True))
        self.assertTrue(self.apply(other, "Sage"))
        stars = guard.Guard(self.first).read(MATERIALS).document["favorites"]
        self.assertEqual({key: True}, stars.get(anna), "the star was lost or saved elsewhere")
        self.assertNotIn(made["Sage"], stars)
        self.assertNotIn(made["Sage"], guard.Guard(other).read(MATERIALS).document.get(
            "favorites", {}))
        sage = self.pane.prefs.library_user
        mine = library_db.document(self.pane.prefs, MATERIALS)
        self.assertTrue(mine.edit("assets", key, name="named by Sage"))
        self.assertTrue(users.delete(self.pane.prefs, sage), "premise: Sage could not leave")
        saved = self.rows(other)[key]
        self.assertEqual(("named by Sage", sage), (saved.get("name"), saved.get(documents.BY)),
                         "a change waiting when its user left was not saved as theirs")

    def test_sw03_a_new_library_is_made_only_in_an_empty_folder(self):
        folder = self.empty_folder()
        test_support.put(folder, "notes.txt", b"the user's own file")
        before = state(folder)
        holder = types.SimpleNamespace(dir=folder, library_user="")
        with test_support.captured_log():
            library_actions.prepare(holder)
            self.assertFalse(self.pane.library.takes_library(folder))
            self.assertFalse(self.apply(folder, "Fern"))
        self.assertEqual(before, state(folder), "a library was started in a folder in use")
        self.assertEqual(self.first, self.pane.library.models_dir)
        os.remove(os.path.join(folder, "notes.txt"))
        self.assertTrue(self.apply(folder, "Fern"), "an empty folder was refused")
        self.assertTrue(os.path.isfile(os.path.join(folder, guard.MASTER)))


class OpenTest(_Pane):
    """Requirements on which library opens, and with whom."""

    def test_sw20_a_library_opens_only_with_one_of_its_own_users(self):
        folder = self.empty_folder()
        self.assertTrue(self.apply(folder, "Fern"))
        fern = self.pane.prefs.library_user
        library_db.flush()
        self.assertEqual({fern: "Fern"}, users.all_users(self.pane.prefs))
        for name, kept in state(folder).items():
            if name in guard.DATABASES:
                stamps = {entry.get(documents.BY) for table in json.loads(kept).values()
                          if isinstance(table, dict) for entry in table.values()
                          if isinstance(entry, dict) and documents.BY in entry}
                self.assertLessEqual(stamps, {fern, ""}, "%s was written by a stranger" % name)
        other, _made = self.library("Sage")
        before = state(other)
        settings = os.path.join(self.pane.prefs.path, "settings.json")
        with open(settings, encoding="utf-8") as handle:
            named = dict(json.load(handle), directory=other, library_user=fern)
        test_support.put(self.pane.prefs.path, "settings.json", json.dumps(named))
        with test_support.captured_log():
            self.pane.library.reload()    # Fern is no user of the library the settings name now
        self.assertEqual(folder, self.pane.library.models_dir, "it opened with a stranger")
        self.assertEqual(before, state(other), "a library not opened was written to")

    def test_sw21_a_library_that_does_not_open_leaves_everything_as_it_was(self):
        other, _made = self.library("Sage")
        user = self.pane.prefs.library_user
        with mock.patch.object(prefs_mod.Prefs, "save", persistence._Persistence.save):
            self.pane.prefs.save()
        kept, before = self.switch_settings(), state(other)
        picked = prefs_window.AmazePrefsState(self.pane.prefs, pane=self.pane)
        picked.pick_library(other)
        test_support.pick_user(picked, "Sage")
        with test_support.refused_at_open(os.path.join(other, guard.MASTER)), \
                mock.patch.object(hou, "ui", mock.MagicMock(), create=True), \
                mock.patch.object(prefs_mod.Prefs, "save", persistence._Persistence.save), \
                test_support.captured_log():
            picked.apply()
        self.assertTrue(picked.changeCount, "a pick that did not open was not left pending")
        self.assertEqual((self.first, user), (self.pane.prefs.dir, self.pane.prefs.library_user))
        self.assertEqual(self.first, self.pane.library.models_dir)
        self.assertEqual(kept, self.switch_settings(), "the settings name the library that failed")
        self.assertEqual(before, state(other), "the library that did not open was written")

    def test_sw22_nothing_switches_before_apply_and_apply_switches_both_once(self):
        other, made = self.library("Sage")
        picked = prefs_window.AmazePrefsState(self.pane.prefs, pane=self.pane)
        picked.pick_library(other)
        test_support.pick_user(picked, "Sage")
        self.assertEqual((self.first, self.first),
                         (self.pane.prefs.dir, self.pane.library.models_dir))
        model = self.pane.material_model
        with mock.patch.object(model, "switch_model_data", wraps=model.switch_model_data) as switch:
            self.assertTrue(self.apply(other, "Sage", state_=picked))
        self.assertEqual((other, made["Sage"]), (self.pane.library.models_dir,
                                                 self.pane.prefs.library_user))
        self.assertEqual(1, switch.call_count, "Apply switched more than once")

    def test_sw24_panels_on_one_library_share_one_set_of_rows(self):
        mine = model_registry.models_for(self.pane.prefs)
        later = prefs_mod.Prefs()
        later.path, later.dir = self.pane.prefs.path, self.first
        self.assertIs(mine["material_model"], model_registry.models_for(later)["material_model"])
        other, _made = self.library("Sage")
        self.assertTrue(self.apply(other, "Sage"))
        joined = prefs_mod.Prefs()
        joined.path, joined.dir = self.pane.prefs.path, other
        self.assertIs(self.pane.material_model, model_registry.models_for(joined)["material_model"],
                      "a panel opened after a switch got a second set of rows")

    def test_sw25_a_database_that_cannot_be_read_does_not_stop_a_switch(self):
        other, _made = self.library("Sage")
        test_support.put(other, NODES, '{"assets": [')
        with test_support.captured_log() as log:
            self.assertTrue(self.apply(other, "Sage"))
            self.assertFalse(self.pane.cop_model.save(), "a save went into an unread database")
        self.assertEqual([], [name for name in library_files.LISTS
                              if not test_support.serves(name, other)])
        self.assertIn(messages.DATABASE_CORRUPT_READ_ONLY % "Nodes", log.messages("alert"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
