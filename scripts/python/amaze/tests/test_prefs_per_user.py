"""Per-device view state is one USER's on this machine: FLAT WHILE NOBODY, BLOCK ONCE SOMEBODY. The flat keys stay the load fallback because they are the migration source. Switching snapshots the OLD user's block, then applies the NEW one over the defaults - and a user with no block here keeps what is on screen. ▸archive/test_prefs_per_user.py
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.prefs import persistence
from amaze.prefs import prefs as prefs_mod
from amaze.tests import test_support

UID_A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
UID_B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


class PerUserCase(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="amaze_peruser_")
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.settings = os.path.join(self.home, "settings.json")

    def write_settings(self, doc):
        with open(self.settings, "w", encoding="utf-8") as handle:
            json.dump(doc, handle)

    def read_settings(self):
        with open(self.settings, encoding="utf-8") as handle:
            return json.load(handle)

    def prefs(self):
        p = prefs_mod.Prefs()
        p.path = self.home
        return p


class TwoUsersKeepTheirOwnViewState(PerUserCase):

    def test_the_active_users_block_is_what_loads(self):
        self.write_settings({
            "library_user": UID_A,
            "users": {
                UID_A: {"view_mode": "list", "thumbsize": 256,
                        "section_filters": {"material": "Redshift"}},
                UID_B: {"view_mode": "grid", "thumbsize": 96},
            }})
        p = self.prefs()
        p.load()
        self.assertEqual("list", p.view_mode,
                         "the active user's block did not load")
        self.assertEqual(256, p.thumbsize)
        self.assertEqual("Redshift", p.section_filter("material"),
                         "a per-user filter did not load")

    def test_a_switch_applies_the_other_block_and_keeps_both(self):
        self.write_settings({
            "library_user": UID_A,
            "users": {
                UID_A: {"view_mode": "list", "thumbsize": 256},
                UID_B: {"view_mode": "grid", "thumbsize": 96},
            }})
        p = self.prefs()
        p.load()
        p.library_user = UID_B
        self.assertEqual(96, p.thumbsize,
                         "switching user did not apply their block")
        self.assertEqual("grid", p.view_mode)
        p.save()
        users = self.read_settings()["users"]
        self.assertEqual(256, users[UID_A].get("thumbsize"),
                         "the previous user's block was lost on a "
                         "switch")
        self.assertEqual(96, users[UID_B].get("thumbsize"))

    def test_a_switch_resets_what_their_block_does_not_carry(self):
        """A key missing from the incoming block means that user never moved it, so inheriting the PREVIOUS user's value bleeds one arrangement into another."""
        self.write_settings({
            "library_user": UID_A,
            "users": {
                UID_A: {"thumbsize": 256, "scroll_speed": 2.0},
                UID_B: {"thumbsize": 96},
            }})
        p = self.prefs()
        p.load()
        self.assertEqual(2.0, p.scroll_speed)
        p.library_user = UID_B
        self.assertEqual(0.75, p.scroll_speed,
                         "a key the incoming block lacks kept the "
                         "previous user's value - one arrangement "
                         "bled into another")

    def test_a_switch_snapshots_unsaved_changes_first(self):
        self.write_settings({
            "library_user": UID_A,
            "users": {
                UID_A: {"thumbsize": 256},
                UID_B: {"thumbsize": 96},
            }})
        p = self.prefs()
        p.load()
        p.thumbsize = 200            # changed, not yet saved
        p.library_user = UID_B
        p.save()
        users = self.read_settings()["users"]
        self.assertEqual(200, users[UID_A].get("thumbsize"),
                         "the switch dropped the outgoing user's "
                         "unsaved change")


class AFlatFileMigratesOnTheFirstSaveWithAUser(PerUserCase):

    def test_flat_values_reach_the_block_and_the_spellings_retire(self):
        self.write_settings({
            "library_user": UID_A,
            "view_mode": "list",
            "thumbsize": 300,
            "scroll_speed": 1.5,
        })
        p = self.prefs()
        p.load()
        self.assertEqual("list", p.view_mode,
                         "the flat fallback stopped loading - the "
                         "migration source was dropped before the "
                         "migration ran")
        self.assertEqual(300, p.thumbsize)
        p.save()
        doc = self.read_settings()
        block = doc.get("users", {}).get(UID_A, {})
        self.assertEqual("list", block.get("view_mode"),
                         "the first save with a user did not carry "
                         "the flat values into the block")
        self.assertEqual(300, block.get("thumbsize"))
        self.assertEqual(1.5, block.get("scroll_speed"))
        for flat in ("view_mode", "thumbsize", "scroll_speed"):
            self.assertNotIn(flat, doc,
                             "a migrated flat spelling was written "
                             "back - two homes for one value")


class NobodyPickedKeepsTheFlatShape(PerUserCase):

    def test_a_userless_save_writes_flat_and_mints_no_block(self):
        """A session that cancelled the ASK dialog keeps full persistence in the old shape - nothing filed under nobody, nothing lost."""
        self.write_settings({"view_mode": "list", "thumbsize": 300})
        p = self.prefs()
        p.load()
        p.thumbsize = 200
        p.save()
        doc = self.read_settings()
        self.assertEqual(200, doc.get("thumbsize"),
                         "a userless save stopped persisting view "
                         "state")
        self.assertEqual("list", doc.get("view_mode"))
        self.assertEqual({}, doc.get("users", {}),
                         "a userless save minted a block under a "
                         "blank key")


class ASwitchToAnUnknownUserKeepsTheCurrentState(PerUserCase):

    def test_a_first_pick_inherits_what_is_on_screen(self):
        """A user with no block on this machine starts from the arrangement in front of them, which covers both the mint and a second machine's first pick."""
        self.write_settings({
            "library_user": UID_A,
            "users": {UID_A: {"thumbsize": 256, "view_mode": "list"}},
        })
        p = self.prefs()
        p.load()
        p.library_user = UID_B          # no block for B anywhere
        self.assertEqual(256, p.thumbsize,
                         "a first pick reset the screen instead of "
                         "inheriting it")
        p.save()
        users = self.read_settings()["users"]
        self.assertEqual(256, users.get(UID_B, {}).get("thumbsize"),
                         "the inherited state was not saved as the "
                         "new user's block")
        self.assertEqual(256, users.get(UID_A, {}).get("thumbsize"))


class TheSectionIntroductionIsPerUser(PerUserCase):

    def test_a_seen_flag_in_the_block_stops_the_introduction(self):
        self.write_settings({
            "library_user": UID_A,
            "users": {UID_A: {
                "enabled_sections": ["material"],
                "enabled_sections_seen_file": True,
            }}})
        p = self.prefs()
        p.load()
        self.assertNotIn("file", p.enabled_sections,
                         "a section this user deliberately disabled "
                         "was re-introduced")

    def test_a_user_without_the_flag_gets_the_introduction_once(self):
        self.write_settings({
            "library_user": UID_A,
            "users": {UID_A: {"enabled_sections": ["material"]}},
        })
        p = self.prefs()
        p.load()
        self.assertIn("file", p.enabled_sections,
                      "a section added after this block was written "
                      "stayed invisible")
        p.save()
        block = self.read_settings()["users"][UID_A]
        self.assertTrue(block.get("enabled_sections_seen_file"),
                        "the introduction was not recorded, so it "
                        "would repeat and an OFF could never stick")


class ABlocksUnknownKeysSurviveTheRebuild(PerUserCase):

    def test_a_newer_builds_block_key_is_kept(self):
        self.write_settings({
            "library_user": UID_A,
            "users": {UID_A: {"thumbsize": 256, "future_key": 7}},
        })
        p = self.prefs()
        p.load()
        p.thumbsize = 200
        p.save()
        block = self.read_settings()["users"][UID_A]
        self.assertEqual(7, block.get("future_key"),
                         "rebuilding the block dropped a key a newer "
                         "build wrote - the courtesy must hold at "
                         "block level too")
        self.assertEqual(200, block.get("thumbsize"))


class TheCopiesFollowTheirUser(PerUserCase):
    """The last-known File copies mirror per-user stores, so they live with the user's other state - in the block once somebody, flat while nobody."""

    FLAT = {
        "library_user": UID_A,
        "file_folders": ["/tex/a/"],
        "file_favorites": ["%s|/tex/a/file.png" % UID_A],
        "file_location_records": {"/tex/a/": {"registered": True,
                                              "recursive": True}},
    }

    def test_the_three_copies_land_in_the_block(self):
        self.write_settings(dict(self.FLAT))
        p = self.prefs()
        p.load()
        self.assertEqual(["/tex/a/"], p.last_known_folders,
                         "the flat copy fallback stopped loading")
        self.assertEqual({"registered": True, "recursive": True},
                         p.last_known_records.get("/tex/a/"))
        p.save()
        doc = self.read_settings()
        block = doc.get("users", {}).get(UID_A, {})
        self.assertEqual(["/tex/a/"], block.get("file_folders"),
                         "the folders copy did not follow its user")
        self.assertEqual(
            {"/tex/a/": {"registered": True, "recursive": True}},
            block.get("file_location_records"))
        self.assertEqual(self.FLAT["file_favorites"],
                         block.get("file_favorites"))
        for flat in ("file_folders", "file_favorites",
                     "file_location_records"):
            self.assertNotIn(flat, doc,
                             "a copied spelling stayed flat beside "
                             "its block home")

    def test_a_userless_save_keeps_the_copies_flat(self):
        flat = dict(self.FLAT)
        flat.pop("library_user")
        self.write_settings(flat)
        p = self.prefs()
        p.load()
        p.save()
        doc = self.read_settings()
        self.assertEqual(["/tex/a/"], doc.get("file_folders"),
                         "a userless save lost the folders copy")
        self.assertEqual(
            {"/tex/a/": {"registered": True, "recursive": True}},
            doc.get("file_location_records"))


class ASaveAsksTheDiskOnlyAboutPathsItCouldReHome(PerUserCase):
    """A settings save asks the disk about a File copy's path only when it lies under a home folder."""

    SHARE = "/Volumes/AmazeProbeShare/projects"

    def _settings(self):
        folders = ["%s/job%d/" % (self.SHARE, n) for n in range(3)]
        return {"library_user": UID_A,
                "users": {UID_A: {
                    "file_folders": folders,
                    "file_favorites": ["%s/job0/tex/f%d.exr" % (self.SHARE, n)
                                       for n in range(5)],
                    "file_location_records": {
                        path: {"registered": True} for path in folders}}}}

    def _share_lookups(self, action):
        from unittest import mock
        asked = []
        real = os.path.exists

        def exists(path):
            if str(path).startswith(self.SHARE):
                asked.append(path)
            return real(path)

        with mock.patch.object(persistence.os.path, "exists", exists):
            action()
        return asked

    def test_a_second_save_asks_the_share_nothing(self):
        self.write_settings(self._settings())
        p = self.prefs()
        p.load()
        p.save()
        before = (list(p.last_known_folders), list(p.last_known_favourites),
                  dict(p.last_known_records))
        asked = self._share_lookups(p.save)
        self.assertEqual([], asked,
                         "a save with no copy changed stat'ed %d share paths"
                         % len(asked))
        self.assertEqual(before, (list(p.last_known_folders),
                                  list(p.last_known_favourites),
                                  dict(p.last_known_records)))

    def test_a_changed_copy_lands_without_asking_the_share(self):
        self.write_settings(self._settings())
        p = self.prefs()
        p.load()
        p.save()
        moved = ["%s/job9/" % self.SHARE]
        asked = self._share_lookups(
            lambda: p.keep_last_known(None, moved, None))
        self.assertEqual([], asked, "a share path cannot be re-homed, yet was stat'ed")
        self.assertEqual(moved, list(p.last_known_folders))

    def test_a_folder_that_appears_after_the_load_is_re_homed_by_the_next_save(self):
        from unittest import mock
        here = tempfile.mkdtemp(prefix="amaze_rehome_")
        self.addCleanup(shutil.rmtree, here, True)
        elsewhere = "/Users/amaze-probe-elsewhere"

        def rehome(path):    # hostos.rehome, with `here` standing in for this machine's home
            candidate = here + path[len(elsewhere):]
            return (candidate if path.startswith(elsewhere + "/")
                    and os.path.exists(candidate) else path)

        stored = elsewhere + "/job/"
        self.write_settings({"library_user": UID_A,
                             "users": {UID_A: {"file_folders": [stored]}}})
        with mock.patch.object(persistence.hostos, "rehome", rehome):
            p = self.prefs()
            p.load()
            p.save()
            self.assertEqual([stored], list(p.last_known_folders),
                             "premise: nothing here to re-home onto yet")
            os.makedirs(os.path.join(here, "job"))
            p.save()
        self.assertEqual([here + "/job/"], list(p.last_known_folders),
                         "a save kept a dead path after its folder appeared here")


class TheFiveDerivedKeysAreGone(PerUserCase):
    """The derived keys were the location record in an older spelling - the record is the one home."""

    FIVE = ("file_folder_names", "file_folder_colors",
            "file_folder_show_all", "file_recursive_folders",
            "file_include_subfolders")

    def test_no_derived_spelling_survives_a_save(self):
        self.write_settings({
            "library_user": UID_A,
            "file_location_records": {"/tex/a/": {"registered": True}},
            "file_folder_names": {"/tex/a/": "Alpha"},
            "file_folder_colors": {"/tex/a/": "#112233"},
            "file_folder_show_all": {"/tex/a/": True},
            "file_recursive_folders": ["/tex/a/"],
            "file_include_subfolders": True,
        })
        p = self.prefs()
        p.load()
        p.save()
        doc = self.read_settings()
        block = doc.get("users", {}).get(UID_A, {})
        for key in self.FIVE:
            self.assertNotIn(key, doc,
                             "%s is still written flat" % key)
            self.assertNotIn(key, block,
                             "%s moved into the block instead of "
                             "dying" % key)

    def test_the_five_die_with_nobody_picked_too(self):
        """Unconditional retirement - these are derived outputs, never migration sources."""
        self.write_settings({
            "file_location_records": {"/tex/a/": {"registered": True}},
            "file_folder_names": {"/tex/a/": "Alpha"},
            "file_include_subfolders": True,
        })
        p = self.prefs()
        p.load()
        p.save()
        doc = self.read_settings()
        for key in self.FIVE:
            self.assertNotIn(key, doc,
                             "%s survived a userless save" % key)
        self.assertEqual(
            {"/tex/a/": {"registered": True}},
            doc.get("file_location_records"),
            "the record the five derive from was lost with them")


class DeletingAUserDropsTheirBlock(PerUserCase):
    """A deleted user's view state leaves settings.json with them, and every other block stays."""

    def _two_users_with_blocks(self):
        from amaze.core import users
        p = test_support.fixture_prefs(self)
        keep = users.create(p, "Cobalt")
        gone = users.create(p, "Sienna")
        for uid in (gone, keep, gone):    # each switch files the user it leaves under their uid
            users.adopt(p, uid)
        held = self._blocks(p)
        self.assertTrue({keep, gone, test_support.FIXTURE_USER} <= set(held),
                        "premise: every user has a block on disk")
        return p, keep, gone

    def _blocks(self, p):
        with open(os.path.join(p.path, "settings.json"),
                  encoding="utf-8") as handle:
            return json.load(handle).get("users", {})

    def test_deleting_another_user_drops_only_their_block(self):
        from amaze.core import users
        p, keep, gone = self._two_users_with_blocks()
        users.adopt(p, keep)
        self.assertTrue(users.delete(p, gone))
        held = self._blocks(p)
        self.assertNotIn(gone, held, "the deleted user's block stayed")
        self.assertIn(keep, held, "a surviving user's block went too")
        self.assertIn(test_support.FIXTURE_USER, held)

    def test_deleting_yourself_drops_your_block_and_no_other(self):
        from amaze.core import users
        p, keep, gone = self._two_users_with_blocks()
        self.assertEqual(gone, p.library_user, "premise: the current user")
        self.assertTrue(users.delete(p, gone))
        held = self._blocks(p)
        self.assertNotIn(gone, held,
                         "deleting the current user filed their state "
                         "back under the deleted uid")
        self.assertIn(keep, held)
        self.assertIn(test_support.FIXTURE_USER, held)

    def test_a_second_pane_does_not_write_the_block_back(self):
        """Another pane's settings, read before the delete, leave the block out of its next save."""
        from amaze.core import users
        p, keep, gone = self._two_users_with_blocks()
        users.adopt(p, keep)
        second = prefs_mod.Prefs()
        second.path = p.path
        second.load()
        self.assertIn(gone, second._users_blocks,
                      "premise: the second pane holds the block")
        self.assertTrue(users.delete(p, gone))
        second.save()
        held = self._blocks(p)
        self.assertNotIn(gone, held,
                         "a second pane wrote the deleted user's block back")
        self.assertIn(keep, held)

    def test_a_user_put_back_and_picked_again_is_saved_again(self):
        """A restored `users.json` can bring a deleted uid back; picking it keeps their view state."""
        from amaze.core import users
        p, keep, gone = self._two_users_with_blocks()
        users.adopt(p, keep)
        self.assertTrue(users.delete(p, gone))
        self.assertTrue(users._store(p).set(gone, {"name": "Sienna"}),
                        "premise: the record is back in users.json")
        users.adopt(p, gone)
        p.view_mode = "list"
        p.save()
        held = self._blocks(p)
        self.assertEqual(
            "list", held.get(gone, {}).get("view_mode"),
            "the user came back and was picked, and their view state "
            "is still left out of every save this session")
        self.assertIn(keep, held)


class EachBlockKnowsItsLibrary(PerUserCase):
    """A block names its user's library, so a user that library stops listing can go."""

    STRANGER = "c0ffee00c0ffee00c0ffee00c0ffee00"

    def setUp(self):
        super().setUp()
        from amaze.core import keyed_store
        keyed_store.release()
        self.addCleanup(keyed_store.release)

    def _library(self):
        from amaze.core import users
        p = test_support.fixture_prefs(self)
        keep = users.create(p, "Cobalt")
        users.adopt(p, keep)
        return p, keep

    def _key(self, p):
        from amaze.helpers import hostos
        return hostos.storage_path_key(p.dir)

    def _settings_of(self, p):
        return os.path.join(p.path, "settings.json")

    def _blocks(self, p):
        with open(self._settings_of(p), encoding="utf-8") as handle:
            return json.load(handle).get("users", {})

    def _rewrite(self, p, change):
        with open(self._settings_of(p), encoding="utf-8") as handle:
            doc = json.load(handle)
        change(doc["users"])
        with open(self._settings_of(p), "w", encoding="utf-8") as handle:
            json.dump(doc, handle)

    def _reopened(self, p):
        again = prefs_mod.Prefs()
        again.path = p.path
        again.load()
        return again

    def test_a_block_records_the_library_it_belongs_to(self):
        p, keep = self._library()
        self.assertEqual(self._key(p), self._blocks(p)[keep].get("library"))

    def test_a_user_deleted_elsewhere_loses_their_block_here(self):
        """Another machine's delete reaches only `users.json`; this machine's next save follows it."""
        from amaze.core import users
        p, keep = self._library()
        gone = users.create(p, "Sienna")
        users.adopt(p, gone)
        users.adopt(p, keep)
        self.assertTrue(users._store(p).retire([gone]),
                        "premise: the record left users.json")
        p.save()
        held = self._blocks(p)
        self.assertNotIn(gone, held,
                         "a user this library no longer lists kept a block")
        self.assertIn(keep, held)

    def test_a_block_from_before_the_field_is_claimed_and_never_pruned(self):
        p, keep = self._library()

        def older(blocks):
            for block in blocks.values():
                block.pop("library", None)
            blocks[self.STRANGER] = {"view_mode": "list"}

        self._rewrite(p, older)
        self._reopened(p).save()
        held = self._blocks(p)
        self.assertEqual(self._key(p), held[keep].get("library"),
                         "a listed user's old block was not claimed")
        self.assertEqual({"view_mode": "list"}, held.get(self.STRANGER),
                         "an unclaimed block was pruned or claimed blind")

    def test_an_unreadable_roster_prunes_nothing(self):
        from amaze.core import keyed_store, users
        p, keep = self._library()
        gone = users.create(p, "Sienna")
        users.adopt(p, gone)
        users.adopt(p, keep)
        with open(os.path.join(p.dir, "users.json"), "w",
                  encoding="utf-8") as handle:
            handle.write('{"users": {"')
        keyed_store.release()
        with test_support.captured_log():
            users.all_users(p)
            p.save()
        self.assertIn(gone, self._blocks(p),
                      "a roster that would not read pruned a block")

    def test_an_empty_roster_prunes_nothing(self):
        from amaze.core import keyed_store, users
        p, keep = self._library()
        with open(os.path.join(p.dir, "users.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"users": {}}, handle)
        keyed_store.release()
        users.all_users(p)
        p.save()
        self.assertIn(keep, self._blocks(p),
                      "a roster listing nobody pruned every block")

    def test_another_librarys_block_is_left_alone(self):
        p, keep = self._library()

        def elsewhere(blocks):
            blocks[self.STRANGER] = {"view_mode": "list",
                                     "library": "~/another_library/"}

        self._rewrite(p, elsewhere)
        self._reopened(p).save()
        self.assertEqual("~/another_library/",
                         self._blocks(p).get(self.STRANGER, {}).get("library"))

    def test_the_user_this_machine_points_at_keeps_their_block(self):
        """Deleted elsewhere while picked here, the block goes once someone else is picked."""
        from amaze.core import users
        p, keep = self._library()
        other = users.create(p, "Sienna")
        self.assertTrue(users._store(p).retire([keep]), "premise")
        p.save()
        self.assertIn(keep, self._blocks(p),
                      "the block of the user this machine is was pruned")
        users.adopt(p, other)
        self.assertNotIn(keep, self._blocks(p))

    def test_a_user_another_houdini_added_keeps_their_block(self):
        """A roster read before another Houdini added a user is stale, never grounds to prune."""
        from amaze.core import keyed_store, users
        p, keep = self._library()
        elsewhere = keyed_store.Store(
            users.SPEC, os.path.join(p.dir, users.USERS_FILE), p)
        self.assertTrue(elsewhere.set(self.STRANGER, {"name": "Sienna"}),
                        "premise: the other Houdini added a user")
        library = self._key(p)
        self._rewrite(p, lambda blocks: blocks.update(
            {self.STRANGER: {"view_mode": "list", "library": library}}))
        p.save()
        self.assertIn(self.STRANGER, self._blocks(p),
                      "premise: the save took the other Houdini's block in")
        p.save()
        self.assertIn(self.STRANGER, self._blocks(p),
                      "a user missing only from a stale roster lost their block")

    def test_a_roster_that_will_not_read_again_prunes_nothing(self):
        from amaze.core import users
        p, keep = self._library()
        gone = users.create(p, "Sienna")
        users.adopt(p, gone)
        users.adopt(p, keep)
        self.assertTrue(users._store(p).retire([gone]), "premise")
        with open(os.path.join(p.dir, users.USERS_FILE), "w",
                  encoding="utf-8") as handle:
            handle.write('{"users": {"')
        p.save()
        self.assertIn(gone, self._blocks(p),
                      "a roster a peer left unreadable pruned from its cache")

    def test_a_merge_keeps_the_field_a_save_did_not_know(self):
        from amaze.core import keyed_store
        p, keep = self._library()
        second = self._reopened(p)
        second._users_blocks[keep].pop("library")
        keyed_store.release()
        p.view_mode = "list"
        p.save()
        second.save()
        self.assertEqual(self._key(p), self._blocks(p)[keep].get("library"),
                         "a writer that did not carry the field erased it")

    def _elsewhere(self):
        """The other Houdini's own open tables, kept between its steps as a second process keeps them."""
        from unittest import mock
        from amaze.core import keyed_store
        tables = self.__dict__.setdefault("_other_tables", {})
        return mock.patch.object(keyed_store, "_open", tables)

    def _two_houdinis(self):
        from amaze.core import users
        p, keep = self._library()
        gone = users.create(p, "Sienna")
        users.adopt(p, gone)
        users.adopt(p, keep)
        return p, keep, gone, self._reopened(p)

    def test_a_stale_houdini_saving_after_a_delete_leaves_the_block_out(self):
        """Another Houdini deletes a user; this one, its roster read before that, saves."""
        from amaze.core import keyed_store, users
        p, keep, gone, other = self._two_houdinis()
        with self._elsewhere():
            self.assertTrue(users.delete(other, gone), "premise: deleted there")
        self.assertIn(gone, keyed_store.opened(users.SPEC, p).everyones(),
                      "premise: this Houdini's roster is stale")
        p.view_mode = "list"
        p.save()
        self.assertNotIn(gone, self._blocks(p),
                         "a stale Houdini wrote a deleted user's block back")
        self.assertIn(keep, self._blocks(p))

    def test_a_delete_that_merges_a_peers_save_leaves_the_block_out(self):
        """This Houdini saved after the other read; the other's delete and both next saves merge."""
        from amaze.core import users
        p, keep, gone, other = self._two_houdinis()
        p.view_mode = "list"
        p.save()
        with self._elsewhere():
            self.assertTrue(users.delete(other, gone), "premise: deleted there")
        self.assertNotIn(gone, self._blocks(p),
                         "the delete's own save merged the block back in")
        p.save()
        with self._elsewhere():
            other.save()
        self.assertNotIn(gone, self._blocks(p),
                         "two Houdinis saving in turn kept a deleted user's block")
        self.assertIn(keep, self._blocks(p))

    def test_a_merged_block_the_rules_spare_is_kept(self):
        """Merged in from disk: another library's block and one without the field both stay."""
        p, keep = self._library()
        p.save()

        def peer(blocks):
            blocks[self.STRANGER] = {"view_mode": "list",
                                     "library": "~/another_library/"}
            blocks[self.STRANGER[::-1]] = {"view_mode": "list"}

        self._rewrite(p, peer)
        p.save()
        held = self._blocks(p)
        self.assertIn(self.STRANGER, held, "another library's block was pruned")
        self.assertIn(self.STRANGER[::-1], held,
                      "a block without the field was pruned")


class TheTableAgreesWithInit(PerUserCase):

    def test_every_table_default_matches_a_fresh_prefs(self):
        """The table and `__init__` each state the defaults, so their agreement is DERIVED rather than trusted."""
        p = self.prefs()
        for stored, (prop, attr, default) in \
                persistence.USER_KEYS.items():
            self.assertEqual(
                default, getattr(p, attr),
                "%s: the USER_KEYS default disagrees with __init__"
                % stored)


if __name__ == "__main__":
    unittest.main()
