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

from PySide6 import QtWidgets                            # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from amaze.core import database                          # noqa: E402
from amaze.core import gradient_library                  # noqa: E402
from amaze.tests import test_support                     # noqa: E402,F401


class _Prefs:
    def __init__(self, directory):
        self.dir = directory
        self.directory = directory


class GradientStaleWriteTest(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        self._write({"categories": ["Warm"],
                     "gradients": [{"name": "ours", "points": []}]})
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
        self._write({"categories": ["Theirs"],
                     "gradients": [{"name": "theirs", "points": []},
                                   {"name": "theirs2", "points": []}]})
        # mtime granularity: make the change unmistakable to a
        # (mtime_ns, size) key rather than relying on timer resolution.
        stat = os.stat(self.path)
        os.utime(self.path, ns=(stat.st_atime_ns,
                                stat.st_mtime_ns + 5_000_000_000))

    def test_a_save_refuses_when_the_file_changed_underneath(self):
        self._touch_from_another_session()
        self.lib._user = [{"name": "mine", "type": "user", "points": []}]
        self.lib._save_user()
        on_disk = self._read()
        names = [g["name"] for g in on_disk["gradients"]]
        self.assertEqual(
            ["theirs", "theirs2"], names,
            "the other session's gradients were overwritten - this is "
            "the silent clobber the guard exists to prevent")

    def test_an_ordinary_save_still_works(self):
        """Guards the guard. A refusal that fires always is not a guard,
        it is an outage - and this section had no tests at all before,
        so nothing would have caught that."""
        self.lib._user = [{"name": "mine", "type": "user", "points": []}]
        self.lib._save_user()
        names = [g["name"] for g in self._read()["gradients"]]
        self.assertEqual(["mine"], names,
                         "an ordinary save was refused")

    def test_two_saves_in_a_row_work(self):
        """The baseline must be refreshed AFTER a write, or our own save
        looks like somebody else's edit on the very next one."""
        self.lib._user = [{"name": "first", "type": "user", "points": []}]
        self.lib._save_user()
        self.lib._user = [{"name": "second", "type": "user", "points": []}]
        self.lib._save_user()
        names = [g["name"] for g in self._read()["gradients"]]
        self.assertEqual(
            ["second"], names,
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
            json.dump({"gradients": "this is not a list"}, fh)
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
        lib._load_failed = True                     # a refusing save
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
        self.dir = tempfile.mkdtemp(prefix="amaze_gicon_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"categories": ["Warm"], "gradients": [
                {"name": "ours", "category": "Warm",
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
            gradient_library.GradientLibrary._entry_thumb_key(
                {"colors": self.lib.entry(self.row)["colors"],
                 "ramp": self.lib.entry(self.row).get("ramp")}))


class GradientCategoryColorTest(unittest.TestCase):
    """Colours on gradient categories (2026-07-31): the sidebar bar and
    the tile band, stored beside the names in gradients.json - the same
    shape every other section uses."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_gcol_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"categories": ["Warm"], "gradients": [
                {"name": "ours", "category": "Warm",
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
        self.dir = tempfile.mkdtemp(prefix="amaze_notesweep_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"categories": [],
                       "gradients": [{"name": "klee", "points": [],
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
        key = notes.note_key("gradient", entry["uid"])
        texts = [item["text"]
                 for item in notes.note_for(self.prefs, key).get(
                     "items", [])
                 if item.get("t") == "text"]
        self.assertIn("Theory: warm against cool.", texts,
                      "the words must survive on the Notes page")
        with open(self.path, encoding="utf-8") as fh:
            saved = json.load(fh)
        by_name = {g["name"]: g for g in saved["gradients"]}
        self.assertNotIn("note", by_name["klee"],
                         "the consumed field may not come back on disk")


class GradientFirstOpenWriteCountTest(unittest.TestCase):
    """First open wrote once per swept note and once per phase. A
    constructor is the worst place for that: it runs before anything
    is on screen, and every write rotates a snapshot, so 39 old notes
    pushed the restore tier's real history out with 39 copies of the
    same minute."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_writestorm_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            # STAMPED already: an unstamped entry earns the backfill a
            # write of its own, correctly, and that would hide whether
            # the SEED still earns one.
            json.dump(
                {"categories": [],
                 "gradients": [{"name": "g%d" % i, "points": [],
                                "uid": "fixtureuid%02d" % i,
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
            key = notes.note_key("gradient", entry["uid"])
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
            all(str(e.get("uid") or "") for e in lib._entries),
            "an entry came out of first open with no identity")
        self.assertLessEqual(
            seen.count("gradients.json"), 2,
            "first open wrote gradients.json %d times; the seed and the "
            "note sweep are one write each and the uid backfill should "
            "add none" % seen.count("gradients.json"))


class GradientTileNameTest(unittest.TestCase):
    """set_tile_name is the gradient's rename path since the Info
    dialog retired (2026-08-01) - narrow, persisted, no-op on blank."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_gradname_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"categories": [],
                       "gradients": [{"name": "klee", "points": []}]},
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

    wrong_shape validates containers on purpose, so `{"gradients":
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
        self._write({"gradients": [42], "categories": []})
        lib = self._library()                       # must not raise
        self.assertEqual(
            [], [e for e in lib._user if not isinstance(e, dict)],
            "a junk row survived into the model")

    def test_the_good_rows_around_it_still_load(self):
        """Skip the bad row, keep the library - the connector's own
        merge policy, applied here."""
        good = {"name": "Warm", "colors": []}
        self._write({"gradients": [good, 42, None, "nope"],
                     "categories": []})
        lib = self._library()
        self.assertEqual(
            ["Warm"], [e.get("name") for e in lib._user],
            "a file with one junk row lost its good gradients too")

    def test_a_survivable_file_is_not_latched_as_failed(self):
        """Skipping rows is not a parse failure: latching here would
        refuse every colour edit for the session over one bad row."""
        self._write({"gradients": [{"name": "Warm", "colors": []}, 42],
                     "categories": []})
        lib = self._library()
        self.assertFalse(getattr(lib, "_load_failed", True),
                         "one junk row latched the whole library "
                         "read-only for the session")


if __name__ == "__main__":
    unittest.main(verbosity=2)
