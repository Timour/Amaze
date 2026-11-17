"""`model_registry.refresh_all` re-reads what another machine wrote, without restarting Houdini."""

import json
import os
import shutil
import tempfile
import unittest

from PySide6 import QtWidgets

from amaze.core import library_files, model_registry, users
from amaze.tests import test_support

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
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
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)

    def path(self, name):
        return os.path.join(self.dir, name)

    def _write(self, name, document):
        with open(self.path(name), "w", encoding="utf-8") as handle:
            json.dump(document, handle)


class AUserMadeElsewhereShowsUpWithoutARestart(_Case):
    """The user list was a snapshot taken when the panel opened."""

    def test_the_user_list_is_stale_until_something_refreshes_it(self):
        self._write(library_files.MASTER, {"users": {"u-me": {"name": "Me"}}})
        self.assertEqual({"u-me": "Me"}, users.all_users(self.prefs))

        self._write(library_files.MASTER, {"users": {"u-me": {"name": "Me"},
                                                     "u-them": {"name": "Colleague"}}})
        self.assertEqual(
            {"u-me": "Me"}, users.all_users(self.prefs),
            "premise: the read already returns it, so nothing here is stale")

        model_registry.refresh_all(self.prefs)

        self.assertEqual(
            {"u-me": "Me", "u-them": "Colleague"}, users.all_users(self.prefs),
            "a user created on another machine is still not listed")


class ThePreferencesDialogListsTheCurrentUsers(unittest.TestCase):
    """Opening Preferences reads the library again, so the picker is current."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.path = os.path.join(self.panel.prefs.dir, library_files.MASTER)

    def _users_on_disk(self):
        with open(self.path, encoding="utf-8-sig") as handle:
            return json.load(handle)

    def test_a_user_another_machine_made_is_in_the_picker(self):
        from amaze.dialogs import prefs_dialog

        self.assertTrue(users.create(self.panel.prefs, "Me"),
                        "premise: the fixture could not create a user")
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
    """The same staleness one layer down: `load()` keeps returning its cached document."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.model = self.panel.material_model
        self.path = os.path.join(self.panel.prefs.dir, library_files.MATERIALS)

    def _document(self):
        with open(self.path, encoding="utf-8-sig") as handle:
            return json.load(handle)

    def test_refresh_all_reaches_every_shared_model(self):
        """What `onActivateInterface` calls when the tab comes back."""
        from amaze.core import model_registry

        self.assertTrue(self.model.save())
        document = self._document()
        document["assets"]["VIA-REGISTRY"] = {"id": "VIA-REGISTRY", "name": "Theirs",
                                              "categories": [], "tags": []}
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=4)

        moved = model_registry.refresh_all()

        self.assertIn("material_model", moved,
                      "refresh_all reported nothing, so nothing was re-read")
        self.assertIn("Theirs", [a.name for a in self.model.assets])

    def test_a_category_another_machine_added_reaches_the_sidebar(self):
        """Another machine's material comes with a category the sidebar must also show."""
        self.assertTrue(self.model.save())
        sidebar = self.panel.category_model
        before = sidebar.rowCount()

        document = self._document()
        document.setdefault("categories", {})["FromElsewhere"] = {"order": 99}
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=4)

        heard = []
        sidebar.modelReset.connect(lambda: heard.append("reset"))
        from amaze.core import model_registry
        self.assertIn("category_model", model_registry.refresh_all(),
                      "the sidebar reported no change")

        self.assertEqual(before + 1, sidebar.rowCount(),
                         "the category is not in the sidebar")
        self.assertTrue(heard, "the rows changed and modelReset was not emitted")

    def test_a_refresh_with_nobody_writing_changes_nothing(self):
        from amaze.core import model_registry
        self.assertTrue(self.model.save())
        before = self.model.rowCount()
        self.assertNotIn("material_model", model_registry.refresh_all(),
                         "nothing changed, yet it re-read")
        self.assertEqual(before, self.model.rowCount())


if __name__ == "__main__":
    unittest.main()
