"""A read notices what another machine wrote, without restarting Houdini."""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from PySide6 import QtWidgets

from amaze.core import keyed_store, users
from amaze.helpers import hostos
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

    def test_a_category_another_machine_added_reaches_the_sidebar(self):
        """A peer's material arrives under a category the sidebar must also have."""
        self.assertTrue(self.model.save())
        sidebar = self.panel.category_model
        before = sidebar.rowCount()

        document = self._document()
        document["categories"].append("FromElsewhere")
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=4)

        heard = []
        sidebar.modelReset.connect(lambda: heard.append("reset"))
        from amaze.core import model_registry
        self.assertIn("category_model", model_registry.refresh_all(),
                      "the sidebar reported no change")

        self.assertEqual(before + 1, sidebar.rowCount(),
                         "the category is not in the sidebar")
        self.assertTrue(heard, "the rows changed and no view was told")

    def test_a_refresh_with_nobody_writing_changes_nothing(self):
        from amaze.core import model_registry
        self.assertTrue(self.model.save())
        before = self.model.rowCount()
        self.assertNotIn("material_model", model_registry.refresh_all(),
                         "nothing moved, yet it re-read")
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


class AnUnreadableFileMetByARefreshWipesNothing(_Case):
    """A sync client's empty placeholder or a half-written file, met when a door refreshes."""

    def _refresh_over(self, damage):
        self._write("users.json", {"users": {"u-me": {"name": "Me"}}})
        store = keyed_store.open_store(users.SPEC, self.prefs)
        base, seen = dict(store._base), store._disk_state
        with open(self.path("users.json"), "wb") as handle:
            handle.write(damage)
        with mock.patch.object(keyed_store.debug, "alert") as spoke:
            moved = store.refresh()
        self.assertEqual({"u-me": "Me"}, users.all_users(self.prefs),
                         "the refresh emptied the table it already held")
        self.assertTrue(store.writable,
                        "the refresh latched the store read-only")
        spoke.assert_not_called()
        self.assertFalse(moved, "an unreadable file was re-read as a change")
        self.assertEqual((base, seen), (store._base, store._disk_state),
                         "the merge base or the fingerprint moved")

    def test_an_empty_placeholder(self):
        self._refresh_over(b"")

    def test_a_half_written_document(self):
        self._refresh_over(b'{"users": {"u-me": ')


class ALockedFileMetByARefreshWipesNothing(_Case):
    """A sync client or a virus scanner holding the file for a moment is not the file being gone."""

    def _held_open(self, locked):
        real_open = open

        def held(path, *args, **kwargs):
            if (isinstance(path, (str, os.PathLike))
                    and os.path.abspath(path) == os.path.abspath(locked)):
                raise PermissionError(13, "Permission denied", str(path))
            return real_open(path, *args, **kwargs)

        return mock.patch("builtins.open", held)

    def test_a_locked_file_keeps_the_table_and_says_nothing(self):
        self._write("users.json", {"users": {"u-me": {"name": "Me"}}})
        store = keyed_store.open_store(users.SPEC, self.prefs)
        base, seen = dict(store._base), store._disk_state
        with self._held_open(self.path("users.json")), \
                mock.patch.object(keyed_store.debug, "alert") as spoke:
            moved = store.refresh()
        self.assertEqual(
            {"moved": False, "rows": {"u-me": "Me"}, "writable": True,
             "alerted": False},
            {"moved": moved, "rows": users.all_users(self.prefs),
             "writable": store.writable, "alerted": spoke.called},
            "a moment's lock was read as the file being gone")
        self.assertEqual((base, seen), (store._base, store._disk_state),
                         "the merge base or the fingerprint moved")

    def test_a_locked_file_is_not_read_as_absent(self):
        self._write("users.json", {"users": {"u-me": {"name": "Me"}}})
        with self._held_open(self.path("users.json")):
            answer = hostos.peer_read(self.path("users.json"))
        self.assertNotEqual(hostos.PEER_ABSENT, answer.verdict,
                            "a file that is there read as gone")

    def test_a_missing_file_still_reads_as_absent(self):
        self.assertEqual(hostos.PEER_ABSENT,
                         hostos.peer_read(self.path("users.json")).verdict)
        under_a_file = os.path.join(self.path("users.json"), "x.json")
        self._write("users.json", {"users": {}})
        self.assertEqual(hostos.PEER_ABSENT,
                         hostos.peer_read(under_a_file).verdict)


if __name__ == "__main__":
    unittest.main()
