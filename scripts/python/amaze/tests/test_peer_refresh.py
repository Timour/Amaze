"""A read notices what another machine wrote, without restarting Houdini."""

import json
import os
import shutil
import tempfile
import unittest

from PySide6 import QtWidgets

from amaze.core import keyed_store, users
from amaze.tests import test_support

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])    # ▸p/first-app-picks-the-platform


class _Prefs:

    def __init__(self, directory):
        self.dir = directory
        self.path = directory
        self.library_user = "u-me"


class _Case(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_peer_refresh_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.prefs = _Prefs(self.dir)
        keyed_store.release()
        self.addCleanup(keyed_store.release)

    def path(self, name):
        return os.path.join(self.dir, name)

    def _write(self, name, document):
        with open(self.path(name), "w", encoding="utf-8") as handle:
            json.dump(document, handle)


class AUserMadeElsewhereShowsUpWithoutARestart(_Case):
    """The user list was a snapshot taken when the panel opened."""

    def test_the_user_list_is_stale_until_something_refreshes_it(self):
        self._write("users.json", {"users": {"u-me": {"name": "Me"}}})
        self.assertEqual({"u-me": "Me"}, users.all_users(self.prefs))

        self._write("users.json", {"users": {"u-me": {"name": "Me"},
                                             "u-them": {"name": "Colleague"}}})
        self.assertEqual(
            {"u-me": "Me"}, users.all_users(self.prefs),
            "premise: the read already saw it, so nothing here is stale")

        keyed_store.refresh_all(self.prefs)

        self.assertEqual(
            {"u-me": "Me", "u-them": "Colleague"}, users.all_users(self.prefs),
            "a user created on another machine is still invisible")


class ThePreferencesDialogSeesTheCurrentPeople(unittest.TestCase):
    """Opening Preferences reads the library again, so the picker is current."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.path = os.path.join(self.panel.prefs.dir, "users.json")

    def _users_on_disk(self):
        with open(self.path, encoding="utf-8-sig") as handle:
            return json.load(handle)

    def test_a_user_another_machine_made_is_in_the_picker(self):
        from amaze.dialogs import prefs_dialog

        self.assertTrue(users.create(self.panel.prefs, "Me"),
                        "premise: the fixture could not mint a user")
        before = users.all_users(self.panel.prefs)
        self.assertNotIn("Colleague", before.values(),
                         "premise: this user already exists")

        document = self._users_on_disk()
        table = document.get("users", document)
        table["u-elsewhere"] = {"name": "Colleague"}
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(document, handle)

        dialog = prefs_dialog.PrefsDialog(self.panel.prefs, panel=self.panel)
        self.addCleanup(dialog.deleteLater)

        names = [dialog.cbb_library_user.itemText(row)
                 for row in range(dialog.cbb_library_user.count())]
        self.assertIn(
            "Colleague", names,
            "the picker still lists the people it read when the panel "
            "opened, so a user made on another machine needs a restart")


class AnAssetSavedElsewhereShowsUpWithoutARestart(unittest.TestCase):
    """The same staleness one layer down: `load()` answers its cached document forever."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.model = self.panel.material_model
        self.path = os.path.join(self.panel.prefs.dir, "library.json")

    def _document(self):
        with open(self.path, encoding="utf-8-sig") as handle:
            return json.load(handle)

    def test_a_row_another_machine_added_arrives_on_refresh(self):
        self.assertTrue(self.model.save(), "premise: the first save failed")
        before = self.model.rowCount()

        document = self._document()
        document["assets"].append({"id": "FROM-ELSEWHERE",
                                   "name": "Their material",
                                   "categories": [], "tags": []})
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=4)

        self.model.refresh()

        self.assertEqual(before + 1, self.model.rowCount(),
                         "a material saved on another machine is invisible "
                         "until Houdini restarts")
        self.assertIn("Their material",
                      [asset.name for asset in self.model.assets])

    def test_the_registry_door_reaches_every_shared_model(self):
        """What `onActivateInterface` calls when the tab comes back."""
        from amaze.core import model_registry

        self.assertTrue(self.model.save())
        document = self._document()
        document["assets"].append({"id": "VIA-THE-DOOR", "name": "Theirs",
                                   "categories": [], "tags": []})
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=4)

        moved = model_registry.refresh_all()

        self.assertIn("material_model", moved,
                      "the door reported nothing, so nothing was re-read")
        self.assertIn("Theirs", [a.name for a in self.model.assets])

    def test_a_refresh_with_nobody_writing_changes_nothing(self):
        self.assertTrue(self.model.save())
        before = self.model.rowCount()
        self.assertFalse(self.model.refresh(), "nothing moved, yet it re-read")
        self.assertEqual(before, self.model.rowCount())


class ARefreshCostsNothingWhenNobodyWrote(_Case):

    def test_an_untouched_file_is_not_re_read(self):
        self._write("users.json", {"users": {"u-me": {"name": "Me"}}})
        store = keyed_store.open_store(users.SPEC, self.prefs)
        self.assertFalse(store.refresh(), "nothing moved, yet it re-read")

    def test_a_changed_file_reports_that_it_re_read(self):
        self._write("users.json", {"users": {"u-me": {"name": "Me"}}})
        store = keyed_store.open_store(users.SPEC, self.prefs)
        self._write("users.json", {"users": {"u-me": {"name": "Renamed"}}})
        self.assertTrue(store.refresh(), "the file moved and it did not say so")

    def test_a_refresh_leaves_the_merge_baseline_on_the_new_file(self):
        """Otherwise the next save reads the refreshed rows as our own edits."""
        self._write("users.json", {"users": {"u-me": {"name": "Me"}}})
        store = keyed_store.open_store(users.SPEC, self.prefs)
        self._write("users.json", {"users": {"u-me": {"name": "Renamed"}}})
        store.refresh()
        self.assertEqual({"name": "Renamed"}, store._base.get("u-me"))


if __name__ == "__main__":
    unittest.main()
