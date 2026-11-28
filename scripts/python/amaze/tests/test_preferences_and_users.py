"""Preferences and users: one test per requirement in docs/requirements/preferences-and-users.md."""

import json
import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

from amaze.core import guard, library_db, library_files, library_settings, users
from amaze.helpers import hostos
from amaze.prefs import persistence, settings_store
from amaze.prefs import prefs as prefs_mod
from amaze.tests import faults, test_support

ANNA, ERIK = "a" * 32, "e" * 32
STARS, FOLDERS = "favorites", "locations"
OTHER_VALUES = {"view_mode": "list", "path_style": "absolute", "icon_line_weight": "feather",
                "geometry_shading_mode": "wireframe", "geometry_bg": "white",
                "accent_color": "#123456", "matx_resolution": "4k"}


class _Settings(unittest.TestCase):
    """A settings folder of its own, and Prefs that read and write it."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.home = tempfile.mkdtemp(prefix="amaze_settings_")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.settings = os.path.join(self.home, "settings.json")

    def prefs(self, load: bool = True) -> prefs_mod.Prefs:
        p = prefs_mod.Prefs()
        p.path = self.home
        if load:
            p.load()
        return p

    def write(self, document) -> None:
        with open(self.settings, "w", encoding="utf-8") as handle:
            handle.write(document if isinstance(document, str) else json.dumps(document))

    def on_disk(self):
        with open(self.settings, "rb") as handle:
            return handle.read()

    def stored(self) -> dict:
        return json.loads(self.on_disk())

    def library(self, *names) -> tuple:
        """A new library with a user for each name, the first picked: (Prefs, [uid, ...])."""
        p = self.prefs()
        p.dir = test_support.scratch_dir("amaze_users_lib_") + "/"
        self.addCleanup(shutil.rmtree, p.dir, True)
        self.assertTrue(prefs_mod.create_library(p.dir))
        made = [users.create(p, name) for name in names]
        users.set_current_user(p, made[0])
        return p, made


class SettingsFileTest(_Settings):
    """Requirements on this computer's settings.json."""

    def test_pr01_a_settings_write_cut_off_anywhere_leaves_it_whole(self):
        self.write({"library_user": ANNA, "users": {ANNA: {"view_mode": "grid"}}})
        before = self.on_disk()
        with faults.CutWrites(self.home) as counting:
            changed = self.prefs()
            changed.view_mode = "list"
            changed.save()
        after = self.on_disk()
        self.assertNotEqual(before, after, "premise: the save changed nothing")
        for torn in (False, True):
            for step in range(1, counting.steps + 1):
                self.write(before.decode("utf-8"))
                cut = self.prefs()
                cut.view_mode = "list"
                with faults.CutWrites(self.home, cut_at=step, torn=torn):
                    cut.save()
                self.assertIn(self.on_disk(), (before, after),
                              "cut at step %d of %d%s" % (step, counting.steps, " torn" * torn))
        self.write("{ ruined")
        with test_support.captured_log():
            ruined = self.prefs()
            ruined.view_mode = "list"
            ruined.save()
        self.assertEqual(b"{ ruined", self.on_disk(), "an unreadable file was written over")
        with open(self.settings + ".unreadable", "rb") as handle:
            self.assertEqual(b"{ ruined", handle.read(), "no copy of it was kept")

    def test_pr20_every_setting_saved_reads_back_the_same(self):
        p = self.prefs()
        p.library_user, p.cache_dir = ANNA, hostos.canonical_path_key(self.home)    # as the file keeps a path
        table = dict(persistence.SHARED_KEYS, **persistence.USER_KEYS)
        for stored, (prop, _attr, default) in table.items():
            if prop is None:
                continue
            if isinstance(default, bool):
                setattr(p, prop, not default)
            elif isinstance(default, int):
                setattr(p, prop, default + 1)
                if getattr(p, prop) == default:
                    setattr(p, prop, default - 1)
            else:
                setattr(p, prop, OTHER_VALUES[stored])
            self.assertNotEqual(default, getattr(p, prop), "%s took no other value" % stored)
        p.thumbsize, p.thumbsize_list, p.enabled_sections = 200, 96, ["code", "material"]
        p.set_section_filter("material", "Karma")
        p.note_library_opened(self.home)
        names = [prop for prop, _attr, _default in table.values() if prop] + [
            "thumbsize", "thumbsize_list", "enabled_sections", "cache_dir", "libraries",
            "library_user"]
        saved = {name: getattr(p, name) for name in names}
        p.save()
        again = self.prefs()
        self.assertEqual(saved, {name: getattr(again, name) for name in names})
        self.assertEqual("Karma", again.section_filter("material"))

    def test_pr21_two_panes_saving_settings_keep_each_others_changes(self):
        home = hostos.canonical_path_key(self.home)
        self.write({"directory": home + "/old", "cache_dir": home + "//cache",    # not as Amaze spells them
                    "library_user": ANNA, "users": {ANNA: {"file_folders": [home + "//a", home + "//b"]}}})
        one, two = self.prefs(), self.prefs()
        one.dir, one.cache_dir, one.show_info = home + "/new/", home + "/moved", True
        one.save()
        two.view_mode = "list"
        two.stage_folder_order([home + "/a"])
        with test_support.refused_at_open(self.settings):    # held by another program a moment
            two.save()
        for save in ("first", "second"):    # the second finds the file as its first left it
            two.save()
            saved = self.stored()
            block = saved["users"][ANNA]
            self.assertEqual((one.dir, one.cache_dir, True, "list", [home + "/a"]), (
                persistence._decode_path(saved["directory"]), persistence._decode_path(saved["cache_dir"]),
                block["show_info"], block["view_mode"], persistence._decode_paths(block["file_folders"])),
                "after pane two's %s save" % save)
        rival, real_write, racing = settings_store.SettingsFile(self.settings), \
            hostos.write_json_atomic, []

        def another_session_saves_meanwhile(*args, **kwargs):
            if not racing:
                racing.append(threading.Thread(target=rival.replace, args=(
                    dict(rival.whole_document(), rival=1),)))
                racing[0].start()
                racing[0].join(0.3)
            return real_write(*args, **kwargs)
        one.sidebar_width = 240
        with mock.patch.object(hostos, "write_json_atomic", another_session_saves_meanwhile):
            one.save()
        racing[0].join()
        saved = self.stored()
        block = saved["users"][ANNA]
        self.assertEqual((1, 240, "list"), (saved.get("rival"), block["sidebar_width"],
                                           block["view_mode"]))

    def test_pr22_a_damaged_or_unknown_settings_file_opens_without_a_library(self):
        for damaged in ("[1, 2]", "{ ruined", json.dumps({"directory": 5, "later": 1})):
            os.makedirs(self.home, exist_ok=True)
            self.write(damaged)
            with test_support.captured_log():
                p = self.prefs(load=False)
                self.assertFalse(p.load(), damaged)
            self.assertEqual("", p.dir, damaged)
            shutil.rmtree(self.home)
        os.makedirs(self.home)
        self.write({"library_user": ANNA, "later": {"kept": 1},
                    "users": {ANNA: {"later_field": 2}}})
        p = self.prefs()
        p.view_mode = "list"
        p.save()
        saved = self.stored()
        self.assertEqual(({"kept": 1}, 2), (saved["later"], saved["users"][ANNA]["later_field"]))
        self.write({"directory": 5, "later": 1})
        with test_support.captured_log():
            self.prefs().save()
        self.assertEqual(("", 1), (self.stored()["directory"], self.stored()["later"]), "the next start")

    def test_pr23_view_state_is_per_user_and_none_is_saved_without_one(self):
        self.write({"library_user": ANNA, "users": {ANNA: {"view_mode": "list"},
                                                    ERIK: {"view_mode": "grid"}}})
        p = self.prefs()
        p.sidebar_width = 240
        p.library_user = ERIK
        self.assertEqual(("grid", 0), (p.view_mode, p.sidebar_width), "Erik got Anna's view")
        p.library_user = ANNA
        self.assertEqual(("list", 240), (p.view_mode, p.sidebar_width), "Anna's view was lost")
        p.library_user = "f" * 32
        self.assertEqual(("list", 240), (p.view_mode, p.sidebar_width),
                         "a first pick did not keep what is on screen")
        p.library_user = ""
        p.view_mode = "grid"
        p.save()
        saved = self.stored()
        self.assertEqual("list", saved["users"]["f" * 32]["view_mode"])
        self.assertFalse(set(persistence.USER_KEYS) & set(saved), "a per-user key saved flat")

    def test_pr26_the_library_list_holds_each_folder_once_the_last_first(self):
        p = self.prefs()
        for folder in ("/libs/one/", "/libs/two/", "/libs/one", "/libs/three/"):
            p.note_library_opened(folder)
        self.assertEqual(["/libs/three/", "/libs/one/", "/libs/two/"], p.libraries)
        kept = test_support.scratch_dir("amaze_listed_")
        self.addCleanup(shutil.rmtree, kept, True)
        p.dir = "/libs/three/"
        p.note_library_opened(kept)
        self.assertTrue(p.remove_libraries([kept, "/libs/three/", "/libs/two/"]))
        self.assertEqual(["/libs/three/", "/libs/one/"], p.libraries,
                         "Remove from List took the open library off, or missed one")
        self.assertTrue(os.path.isdir(kept), "Remove from List touched the folder")
        p.save()
        self.assertEqual(p.libraries, self.prefs().libraries)


class UsersTest(_Settings):
    """Requirements on a library's users."""

    def test_pr02_deleting_a_user_removes_their_favourites_and_folders_only(self):
        p, (anna, erik) = self.library("Anna", "Erik")
        library_settings.set_values(p, {"rendersize": 512})
        own = os.path.join(p.dir, "materials", "Brick__A1")
        test_support.put(own, "A1.mat", b"nodes")
        test_support.put(own, "comments/pasted.png", b"picture")
        for uid in (anna, erik):
            users.set_current_user(p, uid)
            for name in (library_files.MATERIALS, library_files.FILES):
                library_db.document(p, name).put_mine(STARS, "A1", True)
            library_db.document(p, library_files.FILES).put_mine(FOLDERS, "loc:1", {"name": "Job"})
        materials = library_db.document(p, library_files.MATERIALS)
        materials.put("assets", "A1", {"name": "Brick"})
        materials.put("comments", "A1", {"items": [{"t": "image", "src": "pasted.png"}]})
        library_db.flush(p)
        before = test_support.library_state(p.dir)
        self.assertTrue(users.delete(p, erik))
        after = test_support.library_state(p.dir)
        self.assertEqual(set(before), set(after), "a file was added or removed")
        for path, data in before.items():
            if path not in guard.DATABASES:
                self.assertEqual(data, after[path], path)
                continue
            was = json.loads(data)
            if path == guard.MASTER:
                was[users.SECTION].pop(erik)
            for section in (STARS, FOLDERS):
                if section in was:
                    self.assertIn(erik, was[section], "premise: %s holds no %s" % (path, section))
                    was[section].pop(erik)
            self.assertEqual(was, json.loads(after[path]), path)

    def test_pr24_no_two_users_share_a_name_and_a_rename_changes_the_name_only(self):
        p, (anna,) = self.library("Anna")
        self.assertEqual("", users.create(p, "  aNNa "), "a second Anna was made")
        erik = users.create(p, "Erik")
        self.assertTrue(users.uid_shaped(erik))
        library_db.document(p, library_files.MATERIALS).put_mine(STARS, "A1", True)
        library_db.flush(p)
        self.assertFalse(users.rename(p, erik, "ANNA"), "a rename took another user's name")
        self.assertTrue(users.rename(p, anna, "Anna Lund"))
        self.assertEqual({anna: "Anna Lund", erik: "Erik"}, users.all_users(p))
        stars = guard.Guard(p.dir).read(library_files.MATERIALS).document[STARS]
        self.assertEqual({anna: {"A1": True}}, stars, "a rename moved what the user owns")

    def test_pr25_a_deleted_users_view_state_leaves_every_computers_settings(self):
        p, (anna, erik) = self.library("Anna", "Erik")
        there = prefs_mod.Prefs()    # another computer's settings, on the same library
        there.path, there.dir = test_support.scratch_dir("amaze_there_"), p.dir
        self.addCleanup(shutil.rmtree, there.path, True)
        for one in (p, there):
            for uid in (erik, anna):
                users.set_current_user(one, uid)    # each switch saves the user left
        stranger = {"view_mode": "list", "library": "~/another_library/"}
        there._users_blocks["c" * 32] = stranger
        unmarked = self.stored()
        del unmarked["users"][anna]["library"]    # a block saved without its library
        self.write(unmarked)
        pane = self.prefs()    # a second pane here, read before the delete
        self.assertTrue(users.delete(p, erik))
        pane.save()
        self.assertNotIn(erik, self.stored()["users"], "the view state stayed or came back")
        self.assertIn("library", self.stored()["users"][anna], "a user's library is saved with nothing else changed")
        with open(os.path.join(p.dir, guard.MASTER), "rb") as handle:
            roster = handle.read()
        test_support.put(p.dir, guard.MASTER, b'{"users": {"')
        with test_support.captured_log():
            there.save()
        self.assertIn(erik, there._users_blocks, "dropped while the roster could not be read")
        test_support.put(p.dir, guard.MASTER, roster)
        there.save()
        self.assertNotIn(erik, there._users_blocks, "another computer kept it at its next save")
        self.assertEqual(stranger, there._users_blocks["c" * 32], "another library's user went")


if __name__ == "__main__":
    unittest.main(verbosity=2)
