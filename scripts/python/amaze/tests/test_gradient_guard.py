"""gradients.json was the uncovered quarter of the database layer.

`library.json`, `cops.json` and `code.json` all reach disk through
DatabaseConnector and inherit its stale-write guard, its merge and its
membership baseline. `gradients.json` - 290KB, the second largest file
in the library - hand-rolled its own save and inherited NONE of them, so
two sessions editing gradients overwrote each other in silence.

A merge strategy covering three of four databases is a false sense of
safety: it is exactly the shape that makes someone believe the whole
layer is protected.

This pins the guard, both directions. Refusing is not the end state - a
per-field merge is - but refusing is honest, because at the moment of
refusal the other session's write is intact on disk and this one is
still in memory, so nothing has been lost yet.
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

from PySide6 import QtCore, QtWidgets                    # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from amaze.core import category                          # noqa: E402
from amaze.core import database                          # noqa: E402
from amaze.core import gradient_library                  # noqa: E402
from amaze.core import tile_icons                        # noqa: E402
from amaze.tests import test_support                     # noqa: E402,F401


class _Prefs:
    def __init__(self, directory):
        self.dir = directory
        self.directory = directory


class GradientStaleWriteTest(unittest.TestCase):

    def setUp(self):
        # THE CONNECTOR IS ONE INSTANCE PER FILENAME, process-wide.
        # These classes predate gradients having a connector at all, so
        # none of them reset it - and once gradients moved onto it, a
        # fresh model built against a fresh temp dir got the PREVIOUS
        # test's cached document and latches back from `load()`. Every
        # sibling that touches a database already does this.
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        # WITH AN IDENTITY, because the product never writes a row
        # without one - a gradient has an id at birth or from the
        # backfill - and the connector keys its whole union on it, so
        # identity-less fixture rows all collapse into one key and
        # overwrite each other (the second time this line has earned
        # practice.md ▸ A FIXTURE MUST WRITE FILES THE WAY THE
        # PRODUCT DOES).
        self._write({"version": 4, "categories": ["Warm"],
                     "assets": [{"name": "ours", "id": "oursuid",
                                 "points": []}]})
        self.lib = gradient_library.GradientLibrary(_Prefs(self.dir))
        # Only run against a library that actually found the fixture.
        if self.lib._user_file() != self.path:
            self.skipTest("gradient library does not resolve this path")

    def _write(self, data):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)

    def _read(self):
        with open(self.path, encoding="utf-8") as fh:
            return json.load(fh)

    def _touch_from_another_session(self):
        """Another writer replaces the file after we loaded it."""
        self._write({"version": 4, "categories": ["Theirs"],
                     "assets": [{"name": "theirs", "points": [],
                                 "id": "theirsuid1"},
                                {"name": "theirs2", "points": [],
                                 "id": "theirsuid2"}]})
        # mtime granularity: make the change unmistakable to a
        # (mtime_ns, size) key rather than relying on timer resolution.
        stat = os.stat(self.path)
        os.utime(self.path, ns=(stat.st_atime_ns,
                                stat.st_mtime_ns + 5_000_000_000))

    def test_the_other_sessions_gradients_survive_our_save(self):
        """THE CONTRACT CHANGED FROM REFUSE TO MERGE, and it changed
        because this file stopped being the odd one out.

        The hand-built writer serialised `_user` wholesale, so it had
        to REFUSE outright when the file moved underneath it - the
        alternative was erasing the other session. The connector
        three-way merges instead, which is what `library.json`,
        `cops.json` and `code.json` have always done, so both sides now
        survive. That is strictly more than refusing gave: the user
        keeps their edit AND the peer's.
        """
        self._touch_from_another_session()
        self.lib._user = [{"name": "mine", "type": "user",
                           "id": "mineid", "points": []}]
        self.lib._save_user()
        names = [g["name"] for g in self._read()["assets"]]
        for theirs in ("theirs", "theirs2"):
            self.assertIn(
                theirs, names,
                "the other session's gradients were overwritten - the "
                "merge is what replaced the old outright refusal, so "
                "losing them is worse than either")
        self.assertIn("mine", names, "our own edit was dropped")

    def test_an_ordinary_save_still_works(self):
        """Guards the guard. A refusal that fires always is not a guard,
        it is an outage - and this section had no tests at all before,
        so nothing would have caught that."""
        self.lib._user = [{"name": "mine", "type": "user",
                           "id": "mineid", "points": []}]
        self.lib._save_user()
        names = [g["name"] for g in self._read()["assets"]]
        self.assertIn("mine", names, "an ordinary save was refused")

    def test_two_saves_in_a_row_work(self):
        """The baseline must be refreshed AFTER a write, or our own save
        looks like somebody else's edit on the very next one."""
        self.lib._user = [{"name": "first", "type": "user",
                           "id": "firstid", "points": []}]
        self.lib._save_user()
        self.lib._user = [{"name": "second", "type": "user",
                           "id": "secondid", "points": []}]
        self.lib._save_user()
        names = [g["name"] for g in self._read()["assets"]]
        self.assertIn(
            "second", names,
            "the second save was refused - the post-write baseline is "
            "not being refreshed")

    def test_a_missing_file_does_not_block_saving(self):
        """Fails safe the other way: the file being GONE is not another
        session's edit, and refusing there would leave the user unable
        to save anything at all."""
        os.remove(self.path)
        self.lib._user = [{"name": "recreated", "type": "user",
                           "points": []}]
        self.lib._save_user()
        self.assertTrue(os.path.isfile(self.path),
                        "a missing file blocked the save entirely")

    def test_a_deleted_gradient_stays_deleted(self):
        """ABSENCE NO LONGER MEANS DELETE, which is the one contract the
        move onto the connector genuinely changed.

        The hand-built writer serialised `_user` wholesale, so dropping
        an entry from that list WAS the delete. The connector unions
        instead - a row the caller does not mention is kept, because two
        panes share one connector and pane 2's save must not erase what
        pane 1 just added - and a delete therefore has to be said out
        loud through `forget()`. Without this the palette reappears on
        the next save, which is worse than a refused delete: the user
        watched it go.
        """
        gone = self.lib.entry(0)
        name = gone["name"]
        self.lib.remove_user_gradient(0)
        self.lib._user.append({"name": "kept", "type": "user",
                               "id": "keptid", "points": []})
        self.lib._save_user()
        names = [g["name"] for g in self._read()["assets"]]
        self.assertIn("kept", names, "premise: the later save landed")
        self.assertNotIn(
            name, names,
            "the deleted palette came back on the next save - absence "
            "is not a delete through the connector, so it has to be "
            "said out loud")

    def test_the_scratch_file_is_not_left_behind(self):
        self.lib._user = [{"name": "mine", "type": "user", "points": []}]
        self.lib._save_user()
        strays = [n for n in os.listdir(self.dir)
                  if n.startswith("gradients.json")
                  and not n.endswith(".json")
                  and ".bak" not in n]
        self.assertEqual([], strays, "a scratch file survived the save")


class GradientAbsenceAndShapeTest(unittest.TestCase):
    """gradients.json is the one database outside DatabaseConnector, so
    every guard the others inherit had to be given to it by hand - and
    three were missing in different ways.
    """

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_shape_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")

    def _library(self):
        lib = gradient_library.GradientLibrary(_Prefs(self.dir))
        if lib._user_file() != self.path:
            self.skipTest("gradient library does not resolve this path")
        return lib

    def test_repair_and_the_loader_agree_that_the_file_was_here(self):
        """The finding. Both ask "was this file ever here?"; the loader
        asked through its own private call and Repair through the shared
        table, and gradients.json was the one database absent from that
        table - so with the marker present and the file gone, Repair
        said "nothing saved here yet" at the moment the loader had
        latched and refused every colour write."""
        marker = os.path.join(self.dir, gradient_library.GradientLibrary
                              ._SEED_MARKER)
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write("seeded 3 curated palettes\n")
        self.assertFalse(os.path.exists(self.path), "premise: file absent")
        self.assertTrue(
            database.absent_but_known(self.dir, "gradients.json"),
            "the shared table still cannot see that gradients.json was "
            "here - Repair will report a false all-clear")

    def test_a_wrong_shaped_file_does_not_take_the_panel_down(self):
        """Valid JSON, wrong shape. It used to raise straight out of the
        constructor; it must route into the same refusal path a parse
        failure takes."""
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"version": 4, "assets": "this is not a list"}, fh)
        lib = self._library()                       # must not raise
        self.assertTrue(getattr(lib, "_load_failed", False),
                        "a wrong-shaped file loaded as if it were fine, so "
                        "the next save would overwrite it")

    def test_a_top_level_list_does_not_take_the_panel_down(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(["not", "an", "object"], fh)
        lib = self._library()                       # must not raise
        self.assertTrue(getattr(lib, "_load_failed", False))

    def test_the_seed_marker_is_withheld_when_the_save_did_not_land(self):
        """The marker is permanent and is the only trace this file
        leaves. Minting it for a save that never reached disk produces
        marker-present + file-absent, which latches the loader and
        refuses every colour edit for the session - curable only by
        deleting a dotfile the user cannot be expected to know about."""
        lib = self._library()
        # The latch is the CONNECTOR'S now; the model's property only
        # reads it. Setting it there is the same refusing-save state.
        lib._db()._write_blocked = True
        self.addCleanup(setattr, lib._db(), "_write_blocked", False)
        self.assertFalse(lib._save_user(),
                         "_save_user reported success while refusing")

    def test_a_completed_save_reports_success(self):
        """The other direction, so the guard cannot be satisfied by a
        _save_user that simply always says False."""
        lib = self._library()
        self.assertTrue(lib._save_user(),
                        "an ordinary save reported failure")
        self.assertTrue(os.path.exists(self.path))


class GradientTileIconTest(unittest.TestCase):
    """Colors joined Customize 2026-07-31.

    A gradient has no asset id and no file of its own, so unlike every
    other section NO PNG is written - the spec rides on the entry and
    the icon is composed in memory. These are the three things that
    makes true: it is stored, it reaches the tile, and it is
    reversible."""

    def setUp(self):
        test_support.reset_database_singletons()
        # The tile-icon store is a singleton per filename too, and the
        # icon lives THERE now, not on the entry - a store resurrected
        # from a previous test's directory swallows the write and the
        # reload reads an empty one.
        tile_icons.forget_overrides()
        self.dir = tempfile.mkdtemp(prefix="amaze_gicon_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"version": 4, "categories": ["Warm"], "assets": [
                {"name": "ours", "categories": ["Warm"], "id": "oursicon",
                 "colors": [{"name": "red", "hex": "#ff0000"},
                            {"name": "blue", "hex": "#0000ff"}]}]}, fh)
        self.lib = gradient_library.GradientLibrary(_Prefs(self.dir))
        if self.lib._user_file() != self.path:
            self.skipTest("gradient library does not resolve this path")
        self.row = next(
            (r for r in range(self.lib.rowCount())
             if (self.lib.entry(r) or {}).get("name") == "ours"), None)
        if self.row is None:
            self.skipTest("fixture gradient not loaded")

    def test_an_icon_is_stored_and_read_back(self):
        self.assertEqual({}, self.lib.tile_icon(self.row))
        self.assertTrue(self.lib.set_tile_icon(
            self.row, {"name": "layers", "bg": "#4af2a1"}))
        self.assertEqual("layers", self.lib.tile_icon(self.row)["name"])

    def test_the_icon_survives_a_reload(self):
        """It must reach gradients.json - a spec kept only in memory
        looks identical until the panel is reopened."""
        self.lib.set_tile_icon(self.row, {"name": "layers", "bg": "#4af2a1"})
        again = gradient_library.GradientLibrary(_Prefs(self.dir))
        row = next(r for r in range(again.rowCount())
                   if (again.entry(r) or {}).get("name") == "ours")
        self.assertEqual("layers", again.tile_icon(row)["name"])

    def test_the_thumb_key_changes_with_the_icon(self):
        """Same gradient, different picture: without this the shared
        image cache serves whichever was asked for first."""
        plain = self.lib._entry_thumb_key(self.lib.entry(self.row))
        self.lib.set_tile_icon(self.row, {"name": "layers", "bg": "#4af2a1"})
        iconed = self.lib._entry_thumb_key(self.lib.entry(self.row))
        self.assertNotEqual(plain, iconed)

    def test_clearing_brings_the_swatch_back(self):
        self.lib.set_tile_icon(self.row, {"name": "layers", "bg": "#4af2a1"})
        self.lib.set_tile_icon(self.row, {})
        self.assertEqual({}, self.lib.tile_icon(self.row))
        self.assertEqual(
            self.lib._entry_thumb_key(self.lib.entry(self.row)),
            # A bare entry: no uid, so no stored pick and no field -
            # the key a gradient with no icon at all produces.
            self.lib._entry_thumb_key(
                {"colors": self.lib.entry(self.row)["colors"],
                 "ramp": self.lib.entry(self.row).get("ramp")}))


class GradientCategoryColorTest(unittest.TestCase):
    """Colours on gradient categories (2026-07-31): the sidebar bar and
    the tile band, stored beside the names in gradients.json - the same
    shape every other section uses."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_gcol_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"version": 4, "categories": ["Warm"], "assets": [
                {"name": "ours", "categories": ["Warm"], "id": "ourscolor",
                 "colors": [{"name": "red", "hex": "#ff0000"}]}]}, fh)
        self.lib = gradient_library.GradientLibrary(_Prefs(self.dir))
        if self.lib._user_file() != self.path:
            self.skipTest("gradient library does not resolve this path")
        self.row = next(
            (r for r in range(self.lib.rowCount())
             if (self.lib.entry(r) or {}).get("name") == "ours"), None)
        if self.row is None:
            self.skipTest("fixture gradient not loaded")

    def _reload(self):
        return gradient_library.GradientLibrary(_Prefs(self.dir))

    def test_a_colour_is_stored_and_survives_a_reload(self):
        self.assertEqual("", self.lib.category_color_of("Warm"))
        self.assertTrue(self.lib.set_category_color("Warm", "#4af2a1"))
        self.assertEqual("#4af2a1", self._reload().category_color_of("Warm"))

    def test_the_tile_reports_its_category_colour(self):
        """What the grid paints: the colour is set on the CATEGORY and
        read per ROW, so a tile answers for the category it is in."""
        self.lib.set_category_color("Warm", "#4af2a1")
        self.assertEqual("#4af2a1", self.lib.category_color(self.row))

    def test_a_rename_carries_the_colour(self):
        """Keyed by name, so a rename that drops the colour leaves an
        orphan key that silently reattaches if the name comes back."""
        self.lib.set_category_color("Warm", "#4af2a1")
        self.assertTrue(self.lib.rename_user_category("Warm", "Hot"))
        again = self._reload()
        self.assertEqual("#4af2a1", again.category_color_of("Hot"))
        self.assertEqual("", again.category_color_of("Warm"))

    def test_removing_a_category_takes_its_colour(self):
        self.lib.set_category_color("Warm", "#4af2a1")
        self.lib.remove_user_category("Warm")
        self.assertEqual("", self._reload().category_color_of("Warm"))

    def test_clearing_removes_the_colour(self):
        self.lib.set_category_color("Warm", "#4af2a1")
        self.lib.set_category_color("Warm", "")
        self.assertEqual("", self._reload().category_color_of("Warm"))


class GradientNoteSweepTest(unittest.TestCase):
    """The entry-level "note" moved to the Notes store (2026-08-01):
    loading a library that still carries one moves the text onto the
    gradient's Notes page and consumes the field. The Info dialog that
    edited it is gone, and the sweep is what guarantees no words are
    lost on the way out."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_notesweep_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"version": 4, "categories": [],
                       "assets": [{"name": "klee", "points": [],
                                   "id": "kleeid",
                                   "note":
                                   "Theory: warm against cool."}]},
                      fh, indent=1)
        self.prefs = _Prefs(self.dir)

    def test_the_note_lands_on_the_page_and_leaves_the_entry(self):
        lib = gradient_library.GradientLibrary(self.prefs)
        if lib._user_file() != self.path:
            self.skipTest("gradient library does not resolve this path")
        from amaze.core import notes
        entry = next(e for e in lib._entries if e["name"] == "klee")
        self.assertNotIn("note", entry, "the field must be consumed")
        key = notes.note_key("gradient", entry["id"])
        texts = [item["text"]
                 for item in notes.note_for(self.prefs, key).get(
                     "items", [])
                 if item.get("t") == "text"]
        self.assertIn("Theory: warm against cool.", texts,
                      "the words must survive on the Notes page")
        with open(self.path, encoding="utf-8") as fh:
            saved = json.load(fh)
        by_name = {g["name"]: g for g in saved["assets"]}
        self.assertNotIn("note", by_name["klee"],
                         "the consumed field may not come back on disk")


class GradientFirstOpenWriteCountTest(unittest.TestCase):
    """First open wrote once per swept note and once per phase. A
    constructor is the worst place for that: it runs before anything
    is on screen, and every write rotates a snapshot, so 39 old notes
    pushed the restore tier's real history out with 39 copies of the
    same minute."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_writestorm_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            # STAMPED already: an unstamped entry earns the backfill a
            # write of its own, correctly, and that would hide whether
            # the SEED still earns one.
            json.dump(
                # WITH "_All", because every real database carries it -
                # the connector inserts it on load and SAVES when it had
                # to, which is a write of its own and not one this test
                # is about.
                {"version": 4, "categories": ["_All"],
                 "assets": [{"name": "g%d" % i, "points": [],
                             "id": "fixtureuid%02d" % i,
                             "note": "note %d" % i}
                            for i in range(12)]}, fh, indent=1)
        self.prefs = _Prefs(self.dir)

    def _counted_writes(self):
        """Every write in the keyed-store and database engines lands in
        hostos.write_json_atomic, so counting there counts real writes
        rather than calls to a wrapper that might not write."""
        from amaze.helpers import hostos
        seen = []
        real = hostos.write_json_atomic

        def counting(path, *args, **kwargs):
            seen.append(os.path.basename(path))
            return real(path, *args, **kwargs)

        hostos.write_json_atomic = counting
        self.addCleanup(setattr, hostos, "write_json_atomic", real)
        return seen

    def test_twelve_notes_are_swept_in_one_write(self):
        seen = self._counted_writes()
        lib = gradient_library.GradientLibrary(self.prefs)
        if lib._user_file() != self.path:
            self.skipTest("gradient library does not resolve this path")
        self.assertEqual(
            1, seen.count("notes.json"),
            "the sweep wrote notes.json %d times for 12 notes; a "
            "per-note write also rotates a snapshot each time"
            % seen.count("notes.json"))

    def test_every_swept_note_still_arrives(self):
        """Batching must not cost a page - the sweep's contract is
        moved, never dropped."""
        lib = gradient_library.GradientLibrary(self.prefs)
        if lib._user_file() != self.path:
            self.skipTest("gradient library does not resolve this path")
        from amaze.core import notes
        # OURS ONLY: the curated seed runs in this fixture too, and its
        # entries carry notes of their own.
        mine = [e for e in lib._entries
                if e["name"] in {"g%d" % i for i in range(12)}]
        self.assertEqual(12, len(mine), "the fixture entries are missing")
        for entry in mine:
            key = notes.note_key("gradient", entry["id"])
            texts = [item["text"] for item
                     in notes.note_for(self.prefs, key).get("items", [])
                     if item.get("t") == "text"]
            self.assertIn(
                "note %s" % entry["name"][1:], texts,
                "%s lost its note to the batch" % entry["name"])
            self.assertNotIn("note", entry, "the field must be consumed")

    def test_the_uid_backfill_adds_no_write_of_its_own(self):
        """Identity at birth. A seeded entry arrives stamped, so the
        backfill finds nothing and does not save the whole file a
        second time - measured as a WRITE COUNT, because a uid present
        afterwards cannot tell born-stamped from backfilled."""
        seen = self._counted_writes()
        lib = gradient_library.GradientLibrary(self.prefs)
        if lib._user_file() != self.path:
            self.skipTest("gradient library does not resolve this path")
        self.assertTrue(
            all(str(e.get("id") or "") for e in lib._entries),
            "an entry came out of first open with no identity")
        self.assertLessEqual(
            seen.count("gradients.json"), 2,
            "first open wrote gradients.json %d times; the seed and the "
            "note sweep are one write each, and the identity backfill "
            "should add none" % seen.count("gradients.json"))


class GradientTileNameTest(unittest.TestCase):
    """set_tile_name is the gradient's rename path since the Info
    dialog retired (2026-08-01) - narrow, persisted, no-op on blank."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_gradname_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"version": 4, "categories": [],
                       "assets": [{"name": "klee", "points": [],
                                   "id": "kleeid"}]},
                      fh, indent=1)
        self.prefs = _Prefs(self.dir)

    def _row_of(self, lib, name):
        for row in range(len(lib._entries)):
            if lib._entries[row].get("name") == name:
                return row
        self.fail("no gradient named %r in the fixture" % name)

    def test_set_tile_name_renames_and_persists(self):
        lib = gradient_library.GradientLibrary(self.prefs)
        if lib._user_file() != self.path:
            self.skipTest("gradient library does not resolve this path")
        row = self._row_of(lib, "klee")
        self.assertTrue(lib.set_tile_name(row, "Klee two"))
        self.assertEqual("Klee two", lib.tile_name(
            self._row_of(lib, "Klee two")))
        self.assertFalse(lib.set_tile_name(row, "  "),
                         "a blank name must be a no-op")
        again = gradient_library.GradientLibrary(self.prefs)
        self._row_of(again, "Klee two")


class GradientRowShapeTest(unittest.TestCase):
    """A bad ROW, not a bad container (2026-08-02).

    wrong_shape validates containers on purpose, so `{"assets":
    [42]}` parses AND passes it - and then the loader's
    `entry["type"] = "user"` raised TypeError, which is not in its
    `except (OSError, ValueError)`. It escaped the constructor and took
    the whole panel down: the one outcome the load-failure latch exists
    to prevent.

    The seed marker is written in setUp so the curated seeder does not
    run - these tests are about the LOADER, and 348 seeded palettes in
    _user only obscure what is being asserted.
    """

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_rows_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        marker = os.path.join(
            self.dir, gradient_library.GradientLibrary._SEED_MARKER)
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write("seeded\n")

    def _write(self, payload):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def _library(self):
        lib = gradient_library.GradientLibrary(_Prefs(self.dir))
        if lib._user_file() != self.path:
            self.skipTest("gradient library does not resolve this path")
        return lib

    def test_a_non_dict_row_does_not_take_the_panel_down(self):
        self._write({"version": 4, "assets": [42], "categories": []})
        lib = self._library()                       # must not raise
        self.assertEqual(
            [], [e for e in lib._user if not isinstance(e, dict)],
            "a junk row survived into the model")

    def test_the_good_rows_around_it_still_load(self):
        """Skip the bad row, keep the library - the connector's own
        merge policy, applied here."""
        good = {"name": "Warm", "colors": []}
        self._write({"version": 4, "assets": [good, 42, None, "nope"],
                     "categories": []})
        lib = self._library()
        self.assertEqual(
            ["Warm"], [e.get("name") for e in lib._user],
            "a file with one junk row lost its good gradients too")

    def test_a_survivable_file_is_not_latched_as_failed(self):
        """Skipping rows is not a parse failure: latching here would
        refuse every colour edit for the session over one bad row."""
        self._write({"version": 4,
                     "assets": [{"name": "Warm", "colors": []}, 42],
                     "categories": []})
        lib = self._library()
        self.assertFalse(getattr(lib, "_load_failed", True),
                         "one junk row latched the whole library "
                         "read-only for the session")


class TwoRampsWithOneSetOfColoursDoNotShareATile(unittest.TestCase):
    """`_entry_thumb_key` is content-addressed on the hexes and the ramp
    BASES, and `_paint_ramp` reads the ramp's `keys` - the stop
    POSITIONS - in both of its branches. So two palettes holding the
    same colours in different places shared one cache slot and the
    second tile painted the first one's gradient."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_key_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        with open(os.path.join(self.dir, "gradients.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"version": 4, "categories": [], "assets": []}, fh)
        self.lib = gradient_library.GradientLibrary(_Prefs(self.dir))

    def _entry(self, keys):
        return {"type": "user", "name": "n", "categories": [],
                "colors": [{"name": "#ff0000", "hex": "#ff0000"},
                           {"name": "#0000ff", "hex": "#0000ff"}],
                "ramp": {"bases": ["Linear", "Linear"],
                         "keys": keys,
                         "values": [[1, 0, 0], [0, 0, 1]]},
                "id": "rampkey1"}

    def test_moving_a_stop_mints_a_new_key(self):
        even = self.lib._entry_thumb_key(self._entry([0.0, 1.0]))
        moved = self.lib._entry_thumb_key(self._entry([0.0, 0.2]))
        self.assertNotEqual(
            even, moved,
            "two ramps with the same colours in different places share "
            "one cache slot, so the second tile shows the first's")

    def test_the_same_ramp_still_answers_the_same_key(self):
        """Content-addressed means an unchanged palette keeps its
        image - the whole reason the key is not the row number."""
        self.assertEqual(self.lib._entry_thumb_key(self._entry([0.0, 1.0])),
                         self.lib._entry_thumb_key(self._entry([0.0, 1.0])))


class ColorsHonourARefusedSave(unittest.TestCase):
    """`MaterialLibrary.remove_asset` handles a refused write in full -
    the row goes back, `unforget()` clears the pending delete, the row
    is re-added to the connector's document, and the user is told.

    Colors joined the connector on 2026-08-09 and inherited every one
    of its refusal paths without any of that handling: `_save_user()`
    returns True only when the colours reached disk, and eleven of its
    fourteen callers drop the answer. So a delete left the grid, never
    reached gradients.json, said nothing, and came back at the next
    launch."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_refuse_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"version": 4, "categories": ["Warm"],
                       "assets": [
                           {"name": "keep", "id": "keepuid", "points": []},
                           {"name": "doomed", "id": "doomeduid",
                            "points": []}]}, fh, indent=1)
        self.lib = gradient_library.GradientLibrary(_Prefs(self.dir))
        if self.lib._user_file() != self.path:
            self.skipTest("gradient library does not resolve this path")

    def _row_named(self, name):
        for row in range(self.lib.rowCount()):
            entry = self.lib.entry(row)
            if entry and entry.get("name") == name:
                return row
        return -1

    def _on_disk_names(self):
        with open(self.path, encoding="utf-8") as fh:
            document = json.load(fh)
        rows = document.get("assets") or []
        return [r.get("name") for r in rows if isinstance(r, dict)]

    def test_a_refused_delete_puts_the_palette_back(self):
        from unittest.mock import patch

        row = self._row_named("doomed")
        self.assertGreaterEqual(row, 0, "premise: the fixture loaded")
        with patch.object(database.DatabaseConnector, "save",
                          return_value=False):
            self.lib.remove_user_gradient(row)

        self.assertIn("doomed", self._on_disk_names(),
                      "premise: the refusal kept it on disk")
        self.assertGreaterEqual(
            self._row_named("doomed"), 0,
            "the palette left the grid while gradients.json still "
            "listed it - the delete looked done and was not")

    def test_a_refused_delete_is_not_committed_by_the_next_save(self):
        """`forget()` is consumed by `set()` before save() answers, so a
        declined delete sits in the connector's document waiting for ANY
        later write to commit it - the same shape the material path has
        a test for."""
        from unittest.mock import patch

        row = self._row_named("doomed")
        with patch.object(database.DatabaseConnector, "save",
                          return_value=False):
            self.lib.remove_user_gradient(row)
        # Anything at all that writes the file afterwards.
        self.lib.add_user_gradient("later", "", {"values": [], "keys": []})
        self.assertIn(
            "doomed", self._on_disk_names(),
            "the declined delete was committed by an unrelated save")

    def test_a_refused_add_does_not_leave_a_palette_on_screen(self):
        from unittest.mock import patch

        before = self.lib.rowCount()
        with patch.object(database.DatabaseConnector, "save",
                          return_value=False):
            self.lib.add_user_gradient(
                "ghost", "", {"values": [], "keys": []})
        self.assertEqual(
            before, self.lib.rowCount(),
            "a palette that never reached disk stayed in the grid, so "
            "it is gone at the next launch with nothing said")

    def test_an_ordinary_delete_still_works(self):
        """The accept path: the refusal must not be the normal one."""
        row = self._row_named("doomed")
        self.lib.remove_user_gradient(row)
        self.assertEqual(-1, self._row_named("doomed"))
        self.assertNotIn("doomed", self._on_disk_names())


class ColorsHandOverWhatTheMergeAdopted(unittest.TestCase):
    """`take_adopted()` had ONE caller in the package, in library.py.
    Its comment records the measured loss it exists for: a row reaches
    disk, the model never learns of it, and the next save rebuilds the
    list without it.

    Colors merges through the same connector and never drained it."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_adopt_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"version": 4, "categories": ["Warm"],
                       "assets": [{"name": "ours", "id": "oursuid",
                                   "points": []}]}, fh, indent=1)
        self.lib = gradient_library.GradientLibrary(_Prefs(self.dir))
        if self.lib._user_file() != self.path:
            self.skipTest("gradient library does not resolve this path")

    def test_a_palette_the_other_mac_added_reaches_the_grid(self):
        with open(self.path, encoding="utf-8") as fh:
            document = json.load(fh)
        rows = document.get("assets") or []
        rows.append({"name": "from_theirs", "id": "theirsid",
                     "points": [], "colors": []})
        document["assets"] = rows
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(document, fh, indent=1)
        stat = os.stat(self.path)
        os.utime(self.path, ns=(stat.st_atime_ns,
                                stat.st_mtime_ns + 5_000_000_000))

        # Any ordinary edit takes the merge path.
        self.lib.add_user_gradient("mine", "", {"values": [], "keys": []})

        names = [self.lib.entry(r).get("name")
                 for r in range(self.lib.rowCount())]
        self.assertIn(
            "from_theirs", names,
            "the merge adopted the row into gradients.json and never "
            "handed it to the model, so the grid, the sidebar counts "
            "and the filter never saw it - and the next save rebuilds "
            "the list without it")


class ColorsHandOverWhatTheMergeAdoptedIntoCATEGORIES(unittest.TestCase):
    """A peer's category and its colour must survive the save AFTER
    the merge (practice.md > A PARTIAL MIGRATION IS NOT A MIGRATION)."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_cat_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"categories": ["_All", "Warm"],
                       "category_colors": {"Warm": "#c08040"},
                       "assets": [{"name": "ours", "id": "oursid",
                                   "points": [], "colors": []}]}, fh, indent=1)
        self.lib = gradient_library.GradientLibrary(_Prefs(self.dir))
        if self.lib._user_file() != self.path:
            self.skipTest("gradient library does not resolve this path")

    def _peer_adds_a_category(self):
        with open(self.path, encoding="utf-8") as fh:
            document = json.load(fh)
        document.setdefault("categories", []).append("Bronze")
        document.setdefault("category_colors", {})["Bronze"] = "#7b5230"
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(document, fh, indent=1)
        stat = os.stat(self.path)
        os.utime(self.path, ns=(stat.st_atime_ns,
                                stat.st_mtime_ns + 5_000_000_000))

    def _on_disk(self):
        with open(self.path, encoding="utf-8") as fh:
            return json.load(fh)

    def test_a_peers_category_survives_the_SECOND_edit_too(self):
        self._peer_adds_a_category()
        # Edit one merges; edit two is the one that used to erase it.
        self.lib.add_user_gradient("mine", "", {"values": [], "keys": []})
        self.assertIn("Bronze", self._on_disk().get("categories", []),
                      "the merge itself is broken - this test is aimed "
                      "at the save AFTER the merge")
        self.lib.add_user_gradient("mine2", "", {"values": [], "keys": []})
        self.assertIn(
            "Bronze", self._on_disk().get("categories", []),
            "the second Colors edit wrote the other Mac's category out "
            "of existence - _save_user rebuilds `categories` from a "
            "copy taken before the merge ran")

    def test_a_peers_category_COLOUR_survives_the_second_edit_too(self):
        self._peer_adds_a_category()
        self.lib.add_user_gradient("mine", "", {"values": [], "keys": []})
        self.lib.add_user_gradient("mine2", "", {"values": [], "keys": []})
        self.assertEqual(
            "#7b5230",
            self._on_disk().get("category_colors", {}).get("Bronze"),
            "the peer's category colour was written out of existence - "
            "`_category_colors` is a detached dict rebuilt on save")


class TheColorsSidebarIsTheSharedModel(unittest.TestCase):
    """Cop and Code get their sidebar in three lines - a subclass of
    `category.Categories` with its own `DB_FILENAME`. Colors carried a
    standalone list model and twelve category methods of its own, and
    that second implementation is what erased a peer's category."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_side_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        with open(os.path.join(self.dir, "gradients.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"version": 4,
                       "categories": ["_All", "Warm", "Cool"],
                       "assets": [
                           {"id": "a", "name": "one",
                            "categories": ["Warm"], "colors": []},
                           {"id": "b", "name": "two",
                            "categories": ["Warm"], "colors": []},
                       ]}, fh)

    def _sidebar(self):
        # A TRAILING SEPARATOR, because the connector builds
        # `path + filename` - the shape `Prefs.save()` forces on the
        # real field and a bare mkdtemp does not have.
        return gradient_library.GradientCategories(
            preferences=_Prefs(self.dir + os.sep))

    def test_it_subclasses_the_shared_model(self):
        self.assertTrue(
            issubclass(gradient_library.GradientCategories,
                       category.Categories),
            "Colors still has its own sidebar model, so its categories "
            "are a second implementation of the shared one")

    def test_it_reads_the_gradients_database(self):
        self.assertEqual("gradients.json",
                         gradient_library.GradientCategories.DB_FILENAME)

    def test_the_All_row_answers_all(self):
        self.assertEqual(("all", None), self._sidebar().filter_for_row(0))

    def test_a_category_row_answers_its_name(self):
        sidebar = self._sidebar()
        found = [sidebar.filter_for_row(row)
                 for row in range(sidebar.rowCount())]
        self.assertIn(("category", "Warm"), found,
                      "the sidebar cannot name its own category, so a "
                      "click filters the grid to nothing")

    def test_the_counts_come_from_the_shared_walk(self):
        sidebar = self._sidebar()
        # `category.SIDEBAR_COUNT_ROLE`, the module-level role every
        # sidebar answers - the old `COUNT_ROLE` class attribute was
        # itself a Colors-only extra.
        rows = {sidebar.data(sidebar.index(row, 0),
                             QtCore.Qt.ItemDataRole.DisplayRole):
                sidebar.data(sidebar.index(row, 0),
                             category.SIDEBAR_COUNT_ROLE)
                for row in range(sidebar.rowCount())}
        self.assertEqual(2, rows.get("Warm"),
                         "two palettes are filed under Warm: %s" % rows)
        self.assertEqual(0, rows.get("Cool"))


class ColorsNumbersItsRolesLikeTheAssetFamily(unittest.TestCase):
    """Colors answers the role numbers `MultiFilterProxyModel` reads.

    257 category (a list, it is iterated), 258 favourite, 259 kind, 260
    tags, plus +8 and +10 which already match. A filter on any other
    number does nothing.

    The File section is deliberately NOT held to this - its proxy reads
    the model's API, not these numbers.

    Why it lands before the base class moves, and what shadows what:
    practice.md > AN INSTANCE ATTRIBUTE SHADOWS THE CLASS ONE.
    """

    #: What the shared proxy hard-codes, and why each one is read.
    #: Kept as literals rather than reaching into MaterialLibrary,
    #: because MaterialLibrary sets them in __init__ and constructing
    #: one needs a library on disk - and because these ARE the numbers
    #: written into multifilterproxy_model.py's branches.
    SHARED = {
        "CategoryRole": QtCore.Qt.ItemDataRole.UserRole + 1,
        "FavoriteRole": QtCore.Qt.ItemDataRole.UserRole + 2,
        "RendererRole": QtCore.Qt.ItemDataRole.UserRole + 3,
        "TagRole": QtCore.Qt.ItemDataRole.UserRole + 4,
        "CategoryColorRole": QtCore.Qt.ItemDataRole.UserRole + 8,
        "NotesRole": QtCore.Qt.ItemDataRole.UserRole + 10,
    }

    def test_the_four_roles_the_shared_proxy_reads_carry_its_numbers(self):
        model = gradient_library.GradientLibrary
        for name, number in self.SHARED.items():
            with self.subTest(role=name):
                self.assertTrue(
                    hasattr(model, name),
                    "GradientLibrary has no %s; MultiFilterProxyModel "
                    "reads %d and would silently filter nothing"
                    % (name, number))
                self.assertEqual(
                    getattr(model, name), number,
                    "%s is %s, but the shared proxy reads %d for it"
                    % (name, getattr(model, name), number))

    def test_no_two_roles_share_a_number(self):
        """The general form, so a NEW role cannot re-open this.

        A collision here does not raise and does not paint wrong
        immediately - `data()` answers whichever branch it tests first,
        so the symptom is one field quietly returning another field's
        value.
        """
        seen = {}
        for name in dir(gradient_library.GradientLibrary):
            if not name.endswith("Role"):
                continue
            number = getattr(gradient_library.GradientLibrary, name)
            if not isinstance(number, int):
                continue
            self.assertNotIn(
                number, seen,
                "%s and %s are both %d - data() answers whichever it "
                "tests first" % (name, seen.get(number), number))
            seen[number] = name

    def test_the_category_role_answers_a_LIST(self):
        """257 is matched with `for elem in data`, so a bare string
        would match per CHARACTER."""
        directory = tempfile.mkdtemp(prefix="amaze_grad_roles_")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        test_support.reset_database_singletons()
        marker = os.path.join(
            directory, gradient_library.GradientLibrary._SEED_MARKER)
        with open(marker, "w", encoding="utf-8") as handle:
            handle.write("seeded\n")
        with open(os.path.join(directory, "gradients.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"version": 4, "assets": [
                {"id": "aaa", "name": "Test", "categories": ["Warm"],
                 "colors": [{"name": "red", "hex": "#ff0000"}],
                 "type": "user"}]}, handle)
        library = gradient_library.GradientLibrary(_Prefs(directory))
        if library._user_file() != os.path.join(directory,
                                                "gradients.json"):
            self.skipTest("gradient library does not resolve this path")
        role = getattr(gradient_library.GradientLibrary,
                       "CategoryRole", None)
        self.assertIsNotNone(role, "no CategoryRole to answer")
        value = library.data(library.index(0, 0), role)
        self.assertIsInstance(
            value, list,
            "CategoryRole answered %r; the shared proxy iterates it, so "
            "a string matches per character" % (value,))


class EveryCallThePanelMakesOnTheColorsSidebarResolves(unittest.TestCase):
    """Derived, not listed: walk the panel layer for calls on
    `gradient_categories_model` and check each one exists.

    `fcf3977` moved the Colors sidebar onto the shared model and took
    its `refresh()` with it, leaving one caller behind - in the
    save-a-palette-from-a-node flow, after the write, so the palette
    landed and the user got a traceback.

    A list of one method would not have caught the second.
    """

    def _package_root(self):
        return os.path.dirname(os.path.dirname(
            os.path.abspath(gradient_library.__file__)))

    def _calls_on(self, attribute):
        """{method name: [file:line]} for `*.<attribute>.<method>(...)`."""
        import ast
        found = {}
        panel_dir = os.path.join(self._package_root(), "panel")
        for name in sorted(os.listdir(panel_dir)):
            if not name.endswith(".py"):
                continue
            path = os.path.join(panel_dir, name)
            with open(path, "r", encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                outer = node.func
                if not isinstance(outer, ast.Attribute):
                    continue
                inner = outer.value
                if not isinstance(inner, ast.Attribute):
                    continue
                if inner.attr != attribute:
                    continue
                found.setdefault(outer.attr, []).append(
                    "panel/%s:%d" % (name, node.lineno))
        return found

    def test_the_panel_calls_nothing_the_sidebar_model_lacks(self):
        calls = self._calls_on("gradient_categories_model")
        self.assertTrue(
            calls,
            "found no calls at all - the walker stopped matching, which "
            "would make this guard silently vacuous")
        missing = {
            method: sites for method, sites in calls.items()
            if not hasattr(gradient_library.GradientCategories, method)
        }
        self.assertEqual(
            {}, missing,
            "the panel calls these on the Colors sidebar model and the "
            "model does not have them: %s" % missing)


class TheAllMarkerIsNotChurnedOnEverySave(unittest.TestCase):
    """`_load_user` filters `_All` out of `_user_categories` and
    `_save_user` writes that filtered list back, so every Colors edit
    strips the marker from disk - and `DatabaseConnector.
    _normalize_all_category` re-adds it with a FULL save inside
    `GradientLibrary.__init__` on the next launch.

    The cost is not the marker, it is the write: that rewrite spends
    `gradients.json`'s once-per-30-minutes snapshot slot before the
    user has touched anything, so the first half hour of colour edits
    has no restore point behind it."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_all_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"categories": ["_All", "Warm"],
                       "assets": [{"name": "ours", "id": "oursid",
                                   "points": [], "colors": []}]}, fh, indent=1)
        self.lib = gradient_library.GradientLibrary(_Prefs(self.dir))
        if self.lib._user_file() != self.path:
            self.skipTest("gradient library does not resolve this path")

    def test_an_ordinary_edit_leaves_the_All_marker_on_disk(self):
        self.lib.add_user_gradient("mine", "", {"values": [], "keys": []})
        with open(self.path, encoding="utf-8") as fh:
            categories = json.load(fh).get("categories", [])
        self.assertIn(
            "_All", categories,
            "a Colors edit stripped `_All` from gradients.json, so the "
            "next launch re-adds it with a full rewrite and spends the "
            "snapshot slot before the user has done anything")


if __name__ == "__main__":
    unittest.main(verbosity=2)
