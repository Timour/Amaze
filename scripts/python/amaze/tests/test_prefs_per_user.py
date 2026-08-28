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

from amaze.prefs import persistence                  # noqa: E402
from amaze.prefs import prefs as prefs_mod           # noqa: E402
from amaze.tests import test_support                 # noqa: E402,F401

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
