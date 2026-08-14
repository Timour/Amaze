"""Colors runs on the family model, and these pin what that must keep.

`GradientLibrary` subclasses `MaterialLibrary` since the batch-1
rebase, so the stale-write guard, the three-way merge, the adopted-row
handover, the refused-save contracts and the load-failure latch are the
CONNECTOR's and the BASE's - what is pinned here is that Colors
actually rides them (its rows carry `colors`/`ramp` beside the family
fields), plus the rules that are Colors' own: the painted swatch key,
the suppressed load date, the seed marker's honesty, and the sidebar
being the shared `Categories` model.
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
from amaze.core import keyed_store                       # noqa: E402
from amaze.core import tile_icons                        # noqa: E402
from amaze.prefs import prefs                            # noqa: E402
from amaze.tests import test_support                     # noqa: E402,F401

#: The stamp a fixture carries so it is a CURRENT document rather than
#: one the load path has to upgrade. Read from the module, never typed:
#: these were written as a literal `4` and the next bump turned every
#: one of them into a silent test of the migration instead of the
#: behaviour it names (practice.md ▸ A TEST OF A DROP-ON-READ RULE MUST
#: BEAT THE MIGRATION TO THE ROW).
SCHEMA = database.SCHEMA_VERSION


def _fixture_prefs(testcase, directory, user="grad-fixture-uid"):
    """A real Prefs pointed at the fixture dir - the rebased model
    reads the whole preference surface (asset_dir, img_dir, ext,
    thumbsize), so a bare stub no longer stands in. `.dir` keeps its
    trailing separator because the connector concatenates, which is
    the shape `Prefs.save()` forces on the real field. `.path` is
    redirected so nothing ever touches the machine's settings."""
    p = prefs.Prefs()
    p.dir = directory.rstrip(os.sep) + os.sep
    p.path = tempfile.mkdtemp(prefix="amaze_grad_prefs_")
    testcase.addCleanup(shutil.rmtree, p.path, True)
    p.library_user = user
    return p


def _row_named(testcase, lib, name):
    for row in range(lib.rowCount()):
        entry = lib.entry(row)
        if entry and entry.get("name") == name:
            return row
    testcase.fail("no palette named %r in the fixture" % name)


class GradientStaleWriteTest(unittest.TestCase):

    def setUp(self):
        # THE CONNECTOR IS ONE INSTANCE PER FILENAME, process-wide -
        # a fresh model built against a fresh temp dir otherwise gets
        # the PREVIOUS test's cached document and latches.
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        # WITH AN IDENTITY, because the product never writes a row
        # without one and the connector keys its whole union on it
        # (practice.md ▸ A FIXTURE MUST WRITE FILES THE WAY THE
        # PRODUCT DOES).
        self._write({"version": SCHEMA, "categories": ["Warm"],
                     "assets": [{"name": "ours", "id": "oursuid",
                                 "colors": []}]})
        self.lib = gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))

    def _write(self, data):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)

    def _read(self):
        with open(self.path, encoding="utf-8") as fh:
            return json.load(fh)

    def _touch_from_another_session(self):
        """Another writer replaces the file after we loaded it."""
        self._write({"version": SCHEMA, "categories": ["Theirs"],
                     "assets": [{"name": "theirs", "colors": [],
                                 "id": "theirsuid1"},
                                {"name": "theirs2", "colors": [],
                                 "id": "theirsuid2"}]})
        # mtime granularity: make the change unmistakable to a
        # (mtime_ns, size) key rather than relying on timer resolution.
        stat = os.stat(self.path)
        os.utime(self.path, ns=(stat.st_atime_ns,
                                stat.st_mtime_ns + 5_000_000_000))

    def test_the_other_sessions_gradients_survive_our_save(self):
        """The connector three-way merges, which is what the other
        three databases have always done - both sides survive."""
        self._touch_from_another_session()
        self.lib.add_user_gradient("mine", "", {"values": [], "keys": []})
        names = [g["name"] for g in self._read()["assets"]]
        for theirs in ("theirs", "theirs2"):
            self.assertIn(
                theirs, names,
                "the other session's gradients were overwritten - the "
                "merge is what replaced the old outright refusal, so "
                "losing them is worse than either")
        self.assertIn("mine", names, "our own edit was dropped")

    def test_an_ordinary_save_still_works(self):
        """Guards the guard. A refusal that fires always is not a
        guard, it is an outage."""
        self.lib.add_user_gradient("mine", "", {"values": [], "keys": []})
        names = [g["name"] for g in self._read()["assets"]]
        self.assertIn("mine", names, "an ordinary save was refused")

    def test_two_saves_in_a_row_work(self):
        """The baseline must be refreshed AFTER a write, or our own
        save looks like somebody else's edit on the very next one."""
        self.lib.add_user_gradient("first", "", {"values": [], "keys": []})
        self.lib.add_user_gradient("second", "", {"values": [], "keys": []})
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
        self.lib.add_user_gradient("recreated", "",
                                   {"values": [], "keys": []})
        self.assertTrue(os.path.isfile(self.path),
                        "a missing file blocked the save entirely")

    def test_a_deleted_gradient_stays_deleted(self):
        """The connector unions - a row the caller does not mention is
        kept - so a delete has to be said out loud through `forget()`.
        Without that the palette reappears on the next save, which is
        worse than a refused delete: the user watched it go."""
        row = _row_named(self, self.lib, "ours")
        self.lib.remove_user_gradient(row)
        self.lib.add_user_gradient("kept", "", {"values": [], "keys": []})
        names = [g["name"] for g in self._read()["assets"]]
        self.assertIn("kept", names, "premise: the later save landed")
        self.assertNotIn(
            "ours", names,
            "the deleted palette came back on the next save - absence "
            "is not a delete through the connector, so it has to be "
            "said out loud")

    def test_the_scratch_file_is_not_left_behind(self):
        self.lib.add_user_gradient("mine", "", {"values": [], "keys": []})
        strays = [n for n in os.listdir(self.dir)
                  if n.startswith("gradients.json")
                  and not n.endswith(".json")
                  and ".bak" not in n]
        self.assertEqual([], strays, "a scratch file survived the save")


class GradientAbsenceAndShapeTest(unittest.TestCase):
    """The guards every database inherits, exercised on this one -
    plus the marker honesty that is Colors' own."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_shape_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")

    def _library(self):
        return gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))

    def test_repair_and_the_loader_agree_that_the_file_was_here(self):
        """With the seed marker present and the file gone, the shared
        table must say the file was here - or Repair reports a false
        all-clear at the moment the loader has latched."""
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
        """Valid JSON, wrong shape. The survivable load routes it into
        the same refusal a parse failure takes: model empty, connector
        latched, file untouched."""
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"version": SCHEMA, "assets": "this is not a list"},
                      fh)
        lib = self._library()                       # must not raise
        self.assertTrue(getattr(lib, "_load_failed", False),
                        "a wrong-shaped file loaded as if it were fine, "
                        "so the next save would overwrite it")

    def test_a_top_level_list_does_not_take_the_panel_down(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(["not", "an", "object"], fh)
        lib = self._library()                       # must not raise
        self.assertTrue(getattr(lib, "_load_failed", False))

    def test_the_sidebar_survives_the_same_file(self):
        """The sidebar model is constructed right after the library and
        reads the same file - surviving in one constructor and raising
        in the next is the same panel down, one line later."""
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(["not", "an", "object"], fh)
        self._library()
        sidebar = gradient_library.GradientCategories(
            preferences=_fixture_prefs(self, self.dir))  # must not raise
        self.assertEqual(1, sidebar.rowCount(),
                         "the refused document should hold only `_All`")

    def test_the_seed_marker_is_withheld_when_the_save_did_not_land(self):
        """The marker is permanent and is the only trace this file
        leaves. Minting it for a save that never reached disk produces
        marker-present + file-absent, which latches the loader and
        refuses every colour edit for the session."""
        lib = self._library()
        connector = database.DatabaseConnector(lib.DB_FILENAME)
        connector._write_blocked = True
        self.addCleanup(setattr, connector, "_write_blocked", False)
        self.assertFalse(lib.save(),
                         "save reported success while refusing")
        lib.seed_curated_palettes(gradient_library.GradientCategories(
            preferences=_fixture_prefs(self, self.dir)))
        self.assertFalse(
            os.path.exists(os.path.join(
                self.dir, gradient_library.GradientLibrary._SEED_MARKER)),
            "the seed minted its permanent marker for a refused save")

    def test_a_completed_save_reports_success(self):
        """The other direction, so the guard cannot be satisfied by a
        save that simply always says False."""
        lib = self._library()
        self.assertTrue(lib.save(), "an ordinary save reported failure")
        self.assertTrue(os.path.exists(self.path))


class GradientRowRideTest(unittest.TestCase):
    """A palette rides as a `Material` - and what makes that safe is
    that `colors` and `ramp` are carried through verbatim, and that the
    ride invents nothing."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_ride_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"version": SCHEMA, "categories": ["Warm"],
                       "assets": [{"name": "ours", "id": "oursuid",
                                   "categories": ["Warm"],
                                   "colors": [{"name": "red",
                                               "hex": "#ff0000"}],
                                   "ramp": {"keys": [0.0],
                                            "values": [[1, 0, 0]],
                                            "bases": ["Constant"]}}]},
                      fh, indent=1)
        self.lib = gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))

    def _on_disk_row(self, name):
        with open(self.path, encoding="utf-8") as fh:
            for row in json.load(fh).get("assets", []):
                if isinstance(row, dict) and row.get("name") == name:
                    return row
        self.fail("no row named %r on disk" % name)

    def test_colors_and_ramp_survive_a_save_roundtrip(self):
        self.lib.add_user_gradient("mine", "", {"values": [], "keys": []})
        row = self._on_disk_row("ours")
        self.assertEqual([{"name": "red", "hex": "#ff0000"}],
                         row.get("colors"),
                         "the payload was dropped on the Material ride")
        self.assertEqual(["Constant"], row.get("ramp", {}).get("bases"))

    def test_a_loaded_row_does_not_gain_todays_date(self):
        """`Material` mints today's date for a blank - right for an
        asset being born, fabricated history for palettes that predate
        the field. The ride must suppress it."""
        self.assertEqual(
            "", self.lib.assets[0].date,
            "a palette with no stored date claims it was created today")
        self.lib.add_user_gradient("mine", "", {"values": [], "keys": []})
        self.assertEqual(
            "", self._on_disk_row("ours").get("date", ""),
            "the fabricated date reached disk")

    def test_a_freshly_saved_palette_does_get_a_birth_date(self):
        """The suppression is for LOADED rows only - a palette saved
        now is genuinely born now."""
        self.lib.add_user_gradient("mine", "", {"values": [], "keys": []})
        self.assertNotEqual("", self._on_disk_row("mine").get("date", ""),
                            "a new palette should carry its birth date")

    def test_a_legacy_uid_spelling_keeps_its_identity(self):
        """`uid` was the pre-connector spelling; the value keys the
        palette's Comments page and tile icon, so the ride maps it onto
        `id` rather than minting a fresh identity."""
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"version": SCHEMA, "categories": [],
                       "assets": [{"name": "old", "uid": "legacy-value",
                                   "colors": []}]}, fh)
        test_support.reset_database_singletons()
        lib = gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))
        row = _row_named(self, lib, "old")
        self.assertEqual("legacy-value", lib.note_uid(row),
                         "the legacy identity was replaced by a mint")

    def test_a_minted_id_is_persisted_and_stable(self):
        """A row that arrived with no identity gets one - written back,
        so it does not change on every launch under the notes and
        icons keyed by it."""
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"version": SCHEMA, "categories": [],
                       "assets": [{"name": "bare", "colors": []}]}, fh)
        test_support.reset_database_singletons()
        first = gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))
        minted = first.note_uid(_row_named(self, first, "bare"))
        self.assertTrue(minted, "no identity was minted at all")
        test_support.reset_database_singletons()
        again = gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))
        self.assertEqual(
            minted, again.note_uid(_row_named(self, again, "bare")),
            "the minted id was not persisted, so every launch keys the "
            "palette's notes and icon differently")


class GradientTileIconTest(unittest.TestCase):
    """Colors joined Customize 2026-07-31. A palette has no file of its
    own, so unlike every other section NO PNG is written - the spec
    lands in the shared store and the icon is composed in memory. These
    are the three things that makes true: it is stored, it reaches the
    tile, and it is reversible."""

    def setUp(self):
        test_support.reset_database_singletons()
        tile_icons.forget_overrides()
        self.dir = tempfile.mkdtemp(prefix="amaze_gicon_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"version": SCHEMA, "categories": ["Warm"],
                       "assets": [
                {"name": "ours", "categories": ["Warm"], "id": "oursicon",
                 "colors": [{"name": "red", "hex": "#ff0000"},
                            {"name": "blue", "hex": "#0000ff"}]}]}, fh)
        self.prefs = _fixture_prefs(self, self.dir)
        self.lib = gradient_library.GradientLibrary(preferences=self.prefs)
        self.row = _row_named(self, self.lib, "ours")

    def test_an_icon_is_stored_and_read_back(self):
        self.assertEqual({}, self.lib.tile_icon(self.row))
        self.assertTrue(self.lib.set_tile_icon(
            self.row, {"name": "layers", "bg": "#4af2a1"}))
        self.assertEqual("layers", self.lib.tile_icon(self.row)["name"])

    def test_the_icon_survives_a_reload(self):
        """It must reach the store on disk - a spec kept only in memory
        looks identical until the panel is reopened."""
        self.lib.set_tile_icon(self.row, {"name": "layers", "bg": "#4af2a1"})
        test_support.reset_database_singletons()
        tile_icons.forget_overrides()
        again = gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))
        row = _row_named(self, again, "ours")
        self.assertEqual("layers", again.tile_icon(row)["name"])

    def test_no_png_is_written(self):
        """The palette paints in memory; a PNG on disk would be a file
        no cleanup pass accounts for."""
        self.lib.set_tile_icon(self.row, {"name": "layers", "bg": "#4af2a1"})
        pngs = []
        for root, _dirs, names in os.walk(self.dir):
            pngs.extend(n for n in names if n.endswith(".png"))
        self.assertEqual([], pngs, "a palette icon wrote a PNG")

    def test_the_swatch_key_changes_with_the_icon(self):
        """Same palette, different picture: without this the shared
        image cache serves whichever was asked for first."""
        plain = self.lib._swatch_key(self.row)
        self.lib.set_tile_icon(self.row, {"name": "layers", "bg": "#4af2a1"})
        iconed = self.lib._swatch_key(self.row)
        self.assertNotEqual(plain, iconed)

    def test_clearing_brings_the_swatch_back(self):
        plain = self.lib._swatch_key(self.row)
        self.lib.set_tile_icon(self.row, {"name": "layers", "bg": "#4af2a1"})
        self.lib.set_tile_icon(self.row, {})
        self.assertEqual({}, self.lib.tile_icon(self.row))
        self.assertEqual(
            plain, self.lib._swatch_key(self.row),
            "clearing the icon did not return the palette to its own "
            "swatch key, so the cached icon image keeps painting")


class GradientCategoryColorTest(unittest.TestCase):
    """Colours on palette categories: the sidebar model is the writer
    (the same `Categories` machinery every section uses), the library
    reads them per ROW for the tile band, and the rename/remove verbs
    carry them."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_gcol_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"version": SCHEMA, "categories": ["Warm"],
                       "assets": [
                {"name": "ours", "categories": ["Warm"], "id": "ourscolor",
                 "colors": [{"name": "red", "hex": "#ff0000"}]}]}, fh)
        self.prefs = _fixture_prefs(self, self.dir)
        self.lib = gradient_library.GradientLibrary(preferences=self.prefs)
        self.sidebar = gradient_library.GradientCategories(
            preferences=self.prefs)
        self.row = _row_named(self, self.lib, "ours")

    def _reload_sidebar(self):
        test_support.reset_database_singletons()
        return gradient_library.GradientCategories(
            preferences=_fixture_prefs(self, self.dir))

    def test_a_colour_is_stored_and_survives_a_reload(self):
        self.assertEqual("", self.sidebar.color_of("Warm"))
        self.sidebar.set_color("Warm", "#4af2a1")
        self.assertEqual("#4af2a1", self._reload_sidebar().color_of("Warm"))

    def test_the_tile_reports_its_category_colour(self):
        """What the grid paints: the colour is set on the CATEGORY and
        read per ROW, so a tile answers for the category it is in."""
        self.sidebar.set_color("Warm", "#4af2a1")
        self.assertEqual("#4af2a1", self.lib.category_color(self.row))

    def test_a_rename_carries_the_colour(self):
        """Keyed by name, so a rename that drops the colour leaves an
        orphan key that silently reattaches if the name comes back."""
        self.sidebar.set_color("Warm", "#4af2a1")
        self.assertTrue(self.lib.rename_user_category("Warm", "Hot"))
        again = self._reload_sidebar()
        self.assertEqual("#4af2a1", again.color_of("Hot"))
        self.assertEqual("", again.color_of("Warm"))

    def test_removing_a_category_takes_its_colour(self):
        self.sidebar.set_color("Warm", "#4af2a1")
        self.lib.remove_user_category("Warm")
        self.assertEqual("", self._reload_sidebar().color_of("Warm"))


class GradientNoteSweepTest(unittest.TestCase):
    """The entry-level "note" moved to the Notes store (2026-08-01):
    loading a library that still carries one moves the text onto the
    palette's Comments page and consumes the field - no words lost on
    the way out."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_notesweep_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"version": SCHEMA, "categories": [],
                       "assets": [{"name": "klee", "colors": [],
                                   "id": "kleeid",
                                   "note":
                                   "Theory: warm against cool."}]},
                      fh, indent=1)
        self.prefs = _fixture_prefs(self, self.dir)

    def test_the_note_lands_on_the_page_and_leaves_the_entry(self):
        lib = gradient_library.GradientLibrary(preferences=self.prefs)
        from amaze.core import notes
        row = _row_named(self, lib, "klee")
        key = notes.note_key("gradient", lib.note_uid(row))
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
    constructor is the worst place for that: every write rotates a
    snapshot, so 39 old notes pushed the restore tier's real history
    out with 39 copies of the same minute."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_writestorm_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            # STAMPED ids and WITH "_All", so neither the id persist
            # nor the connector's `_All` normalisation earns a write
            # this test is not about.
            json.dump(
                {"version": SCHEMA, "categories": ["_All"],
                 "assets": [{"name": "g%d" % i, "colors": [],
                             "id": "fixtureuid%02d" % i,
                             "note": "note %d" % i}
                            for i in range(12)]}, fh, indent=1)
        self.prefs = _fixture_prefs(self, self.dir)

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
        gradient_library.GradientLibrary(preferences=self.prefs)
        self.assertEqual(
            1, seen.count("notes.json"),
            "the sweep wrote notes.json %d times for 12 notes; a "
            "per-note write also rotates a snapshot each time"
            % seen.count("notes.json"))

    def test_every_swept_note_still_arrives(self):
        """Batching must not cost a page - the sweep's contract is
        moved, never dropped."""
        lib = gradient_library.GradientLibrary(preferences=self.prefs)
        from amaze.core import notes
        for i in range(12):
            row = _row_named(self, lib, "g%d" % i)
            key = notes.note_key("gradient", lib.note_uid(row))
            texts = [item["text"] for item
                     in notes.note_for(self.prefs, key).get("items", [])
                     if item.get("t") == "text"]
            self.assertIn("note %d" % i, texts,
                          "g%d lost its note to the batch" % i)

    def test_stamped_rows_cost_no_identity_write(self):
        """Identity from birth: rows that arrive stamped give the id
        persist nothing to do, so it must not save the whole file -
        measured as a WRITE COUNT, because an id present afterwards
        cannot tell born-stamped from backfilled."""
        seen = self._counted_writes()
        gradient_library.GradientLibrary(preferences=self.prefs)
        self.assertLessEqual(
            seen.count("gradients.json"), 1,
            "first open wrote gradients.json %d times; the note sweep "
            "is one write and the identity persist should add none"
            % seen.count("gradients.json"))


class GradientTileNameTest(unittest.TestCase):
    """set_tile_name is the palette's rename path - inherited from the
    family since the rebase: narrow, persisted, no-op on blank."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_gradname_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"version": SCHEMA, "categories": [],
                       "assets": [{"name": "klee", "colors": [],
                                   "id": "kleeid"}]},
                      fh, indent=1)
        self.prefs = _fixture_prefs(self, self.dir)

    def test_set_tile_name_renames_and_persists(self):
        lib = gradient_library.GradientLibrary(preferences=self.prefs)
        row = _row_named(self, lib, "klee")
        self.assertTrue(lib.set_tile_name(row, "Klee two"))
        self.assertEqual("Klee two", lib.tile_name(
            _row_named(self, lib, "Klee two")))
        self.assertFalse(lib.set_tile_name(row, "  "),
                         "a blank name must be a no-op")
        test_support.reset_database_singletons()
        again = gradient_library.GradientLibrary(preferences=self.prefs)
        _row_named(self, again, "Klee two")


class GradientRowShapeTest(unittest.TestCase):
    """A bad ROW, not a bad container: the connector skips what it
    cannot read, keeps the good rows, and does not latch the library
    read-only over one junk entry."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_rows_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")

    def _write(self, payload):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def _library(self):
        return gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))

    def test_a_non_dict_row_does_not_take_the_panel_down(self):
        self._write({"version": SCHEMA, "assets": [42], "categories": []})
        lib = self._library()                       # must not raise
        self.assertEqual(0, lib.rowCount(),
                         "a junk row survived into the model")

    def test_the_good_rows_around_it_still_load(self):
        """Skip the bad row, keep the library - the connector's own
        merge policy, applied here."""
        good = {"name": "Warm", "colors": [], "id": "warmid"}
        self._write({"version": SCHEMA, "assets": [good, 42, None, "nope"],
                     "categories": []})
        lib = self._library()
        self.assertEqual(
            ["Warm"],
            [lib.entry(r).get("name") for r in range(lib.rowCount())],
            "a file with one junk row lost its good gradients too")

    def test_a_survivable_file_is_not_latched_as_failed(self):
        """Skipping rows is not a parse failure: latching here would
        refuse every colour edit for the session over one bad row."""
        self._write({"version": SCHEMA,
                     "assets": [{"name": "Warm", "colors": [],
                                 "id": "warmid"}, 42],
                     "categories": []})
        lib = self._library()
        self.assertFalse(getattr(lib, "_load_failed", True),
                         "one junk row latched the whole library "
                         "read-only for the session")


class TwoRampsWithOneSetOfColoursDoNotShareATile(unittest.TestCase):
    """The swatch key is content-addressed on the hexes, the ramp BASES
    and the stop POSITIONS - two palettes holding the same colours in
    different places must not share a cache slot, or the second tile
    paints the first one's gradient."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_key_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def _library_with(self, keys_a, keys_b):
        def _row(tag, keys):
            return {"name": tag, "categories": [], "id": tag,
                    "colors": [{"name": "#ff0000", "hex": "#ff0000"},
                               {"name": "#0000ff", "hex": "#0000ff"}],
                    "ramp": {"bases": ["Linear", "Linear"],
                             "keys": keys,
                             "values": [[1, 0, 0], [0, 0, 1]]}}
        with open(os.path.join(self.dir, "gradients.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"version": SCHEMA, "categories": [],
                       "assets": [_row("a", keys_a), _row("b", keys_b)]},
                      fh)
        return gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))

    def test_moving_a_stop_mints_a_new_key(self):
        lib = self._library_with([0.0, 1.0], [0.0, 0.2])
        self.assertNotEqual(
            lib._swatch_key(0), lib._swatch_key(1),
            "two ramps with the same colours in different places share "
            "one cache slot, so the second tile shows the first's")

    def test_the_same_ramp_still_answers_the_same_key(self):
        """Content-addressed means an unchanged palette keeps its
        image - the whole reason the key is not the row number."""
        lib = self._library_with([0.0, 1.0], [0.0, 1.0])
        a, b = lib._swatch_key(0), lib._swatch_key(1)
        self.assertEqual(a[1:], b[1:],
                         "identical content answered different keys")


class AColourStarSurvivesAReloadTest(unittest.TestCase):
    """Colors stars go through the ONE favourites store, tagged with
    their owner, like every section (ROADMAP line 21). The record field
    is dead: nothing writes it, and the schema step strips what older
    documents still carry."""

    def setUp(self):
        test_support.reset_database_singletons()
        keyed_store.release()
        self.addCleanup(keyed_store.release)
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_star_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")

    def _write(self, document):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(document, fh, indent=1)

    def _library(self, user="grad-star-uid"):
        return gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir, user=user))

    def _one_warm_palette(self):
        self._write({"version": SCHEMA, "categories": ["Warm"],
                     "assets": [{"name": "warm", "id": "warmid",
                                 "categories": ["Warm"], "colors": []}]})

    def _disk_rows(self):
        with open(self.path, encoding="utf-8") as fh:
            return json.load(fh).get("assets", [])

    def test_a_star_lands_in_the_store_and_survives_a_reload(self):
        self._one_warm_palette()
        lib = self._library()
        lib.toggle_favorite(_row_named(self, lib, "warm"))
        self.assertTrue(lib.is_favorite(_row_named(self, lib, "warm")),
                        "the toggle did not light the star it just set")
        # The SHARED record gained nothing on disk. A star that reaches
        # gradients.json is everyone's again.
        lib.save()
        self.assertFalse(
            any("favorite" in row for row in self._disk_rows()
                if isinstance(row, dict)),
            "the star reached gradients.json - the shared document "
            "carries per-user state again")
        # A fresh session reads it back out of the library store.
        test_support.reset_database_singletons()
        keyed_store.release()
        again = self._library()
        self.assertTrue(
            again.is_favorite(_row_named(self, again, "warm")),
            "the star did not survive a reload through the store")

    def test_the_step_takes_a_star_off_a_version_5_document(self):
        """Every star toggled between schema 5 and the store move
        landed back on the shared document; the v5->v6 step takes those
        off - without it they sit there forever, readable by nothing
        and shared by everyone."""
        self._write({"version": 5, "categories": ["Warm"],
                     "assets": [{"name": "warm", "id": "warmid",
                                 "categories": ["Warm"], "colors": [],
                                 "favorite": True}]})
        lib = self._library()
        row = _row_named(self, lib, "warm")
        lib.save()
        self.assertFalse(
            any("favorite" in r for r in self._disk_rows()
                if isinstance(r, dict)),
            "a version-5 record star survived the load - the step that "
            "retires the field did not run")
        self.assertFalse(
            lib.is_favorite(row),
            "a stripped record star still reads as a favourite - the "
            "read is answering the record, not the store")

    def test_no_user_picked_means_no_star_and_no_write(self):
        self._one_warm_palette()
        lib = self._library(user="")
        lib.toggle_favorite(_row_named(self, lib, "warm"))
        self.assertFalse(
            lib.is_favorite(_row_named(self, lib, "warm")),
            "a machine with nobody picked lit a star - the store filed "
            "it under a blank tag, which is an ABSENT user, not a "
            "shared one")
        self.assertFalse(
            os.path.exists(os.path.join(self.dir, "favourites.json")),
            "a refused star still created the favourites store")


class ColorsHonourARefusedSave(unittest.TestCase):
    """A refused write is honoured in full: the row goes back (or never
    stays), the pending delete is taken back out of the connector, and
    the user is told - the base model's contract, ridden by Colors."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_refuse_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"version": SCHEMA, "categories": ["Warm"],
                       "assets": [
                           {"name": "keep", "id": "keepuid", "colors": []},
                           {"name": "doomed", "id": "doomeduid",
                            "colors": []}]}, fh, indent=1)
        self.lib = gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))

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
        """`forget()` is consumed by `set()` before save() answers, so
        a declined delete sits in the connector's document waiting for
        ANY later write to commit it."""
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
    """A row another session wrote reaches disk through the merge and
    must reach the MODEL too - `take_adopted()` drained after every
    save, or the next save rebuilds the list without it."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_adopt_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"version": SCHEMA, "categories": ["Warm"],
                       "assets": [{"name": "ours", "id": "oursuid",
                                   "colors": []}]}, fh, indent=1)
        self.lib = gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))

    def test_a_palette_the_other_mac_added_reaches_the_grid(self):
        with open(self.path, encoding="utf-8") as fh:
            document = json.load(fh)
        rows = document.get("assets") or []
        rows.append({"name": "from_theirs", "id": "theirsid",
                     "colors": []})
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
    the merge (practice.md ▸ A PARTIAL MIGRATION IS NOT A MIGRATION)."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_cat_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"categories": ["_All", "Warm"],
                       "category_colors": {"Warm": "#c08040"},
                       "assets": [{"name": "ours", "id": "oursid",
                                   "colors": []}]}, fh, indent=1)
        self.lib = gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))

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
            "the second Colors edit wrote the other machine's category "
            "out of existence - the model holds a detached copy of the "
            "category list")

    def test_a_peers_category_COLOUR_survives_the_second_edit_too(self):
        self._peer_adds_a_category()
        self.lib.add_user_gradient("mine", "", {"values": [], "keys": []})
        self.lib.add_user_gradient("mine2", "", {"values": [], "keys": []})
        self.assertEqual(
            "#7b5230",
            self._on_disk().get("category_colors", {}).get("Bronze"),
            "the peer's category colour was written out of existence - "
            "the colour table is a detached dict rebuilt on save")


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
            json.dump({"version": SCHEMA,
                       "categories": ["_All", "Warm", "Cool"],
                       "assets": [
                           {"id": "a", "name": "one",
                            "categories": ["Warm"], "colors": []},
                           {"id": "b", "name": "two",
                            "categories": ["Warm"], "colors": []},
                       ]}, fh)

    def _sidebar(self):
        return gradient_library.GradientCategories(
            preferences=_fixture_prefs(self, self.dir))

    def test_it_subclasses_the_shared_model(self):
        self.assertTrue(
            issubclass(gradient_library.GradientCategories,
                       category.Categories),
            "Colors still has its own sidebar model, so its categories "
            "are a second implementation of the shared one")

    def test_the_library_subclasses_the_shared_model_too(self):
        """The batch-1 target itself: the Colors MODEL is the family's,
        so every engine guard is inherited rather than hand-kept."""
        from amaze.core import library
        self.assertTrue(
            issubclass(gradient_library.GradientLibrary,
                       library.MaterialLibrary),
            "GradientLibrary is standalone again - 51 engine guards "
            "stop applying to Colors the day that happens")

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
        rows = {sidebar.data(sidebar.index(row, 0),
                             QtCore.Qt.ItemDataRole.DisplayRole):
                sidebar.data(sidebar.index(row, 0),
                             category.SIDEBAR_COUNT_ROLE)
                for row in range(sidebar.rowCount())}
        self.assertEqual(2, rows.get("Warm"),
                         "two palettes are filed under Warm: %s" % rows)
        self.assertEqual(0, rows.get("Cool"))


class ColorsNumbersItsRolesLikeTheAssetFamily(unittest.TestCase):
    """Colors answers the role numbers the shared proxy reads - since
    the rebase, by INHERITING them (test_role_numbers holds the whole
    family table; this pins the two Colors-specific facts left)."""

    def test_the_family_roles_are_inherited_not_redeclared(self):
        """A redeclaration is a second table kept equal by hand - the
        shape the rebase removed."""
        own = vars(gradient_library.GradientLibrary)
        redeclared = [name for name in (
            "IdRole", "CategoryRole", "FavoriteRole", "RendererRole",
            "TagRole", "DateRole", "RendererLabelRole",
            "CategoryColorRole", "NotesRole") if name in own]
        self.assertEqual(
            [], redeclared,
            "GradientLibrary redeclares %s - inherited roles cannot "
            "drift, redeclared ones can" % redeclared)

    def test_no_two_roles_share_a_number(self):
        """The 258 collision of 2026-08-12, held shut: data() answers
        whichever branch it tests first, so a collision is one field
        quietly returning another field's value."""
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
        with open(os.path.join(directory, "gradients.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"version": SCHEMA, "categories": ["Warm"],
                       "assets": [
                {"id": "aaa", "name": "Test", "categories": ["Warm"],
                 "colors": [{"name": "red", "hex": "#ff0000"}]}]}, handle)
        lib = gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, directory))
        value = lib.data(lib.index(0, 0), lib.CategoryRole)
        self.assertIsInstance(
            value, list,
            "CategoryRole answered %r; the shared proxy iterates it, so "
            "a string matches per character" % (value,))


class EveryCallThePanelMakesOnTheColorsSidebarResolves(unittest.TestCase):
    """Derived, not listed: walk the panel layer for calls on
    `gradient_categories_model` and check each one exists. A list of
    one method would not have caught the second stale caller."""

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

    def test_the_panel_calls_nothing_the_library_model_lacks(self):
        """The same walk for the asset model - the rebase deleted
        methods, and a caller left behind is a traceback after a real
        gesture."""
        calls = self._calls_on("gradient_model")
        self.assertTrue(calls, "the walker stopped matching")
        missing = {
            method: sites for method, sites in calls.items()
            if not hasattr(gradient_library.GradientLibrary, method)
        }
        self.assertEqual(
            {}, missing,
            "the panel calls these on the Colors model and the model "
            "does not have them: %s" % missing)


class TheAllMarkerIsNotChurnedOnEverySave(unittest.TestCase):
    """`_All` stays in the stored list; the view edge filters it. A
    save that strips it makes the next launch re-add it with a full
    rewrite, spending the snapshot slot before the user has touched
    anything."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_all_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"categories": ["_All", "Warm"],
                       "assets": [{"name": "ours", "id": "oursid",
                                   "colors": []}]}, fh, indent=1)
        self.lib = gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))

    def test_an_ordinary_edit_leaves_the_All_marker_on_disk(self):
        self.lib.add_user_gradient("mine", "", {"values": [], "keys": []})
        with open(self.path, encoding="utf-8") as fh:
            categories = json.load(fh).get("categories", [])
        self.assertIn(
            "_All", categories,
            "a Colors edit stripped `_All` from gradients.json, so the "
            "next launch re-adds it with a full rewrite and spends the "
            "snapshot slot before the user has done anything")

    def test_the_view_list_still_hides_it(self):
        self.assertNotIn("_All", self.lib.user_categories(),
                         "the save dialog would offer the marker as a "
                         "category")


if __name__ == "__main__":
    unittest.main(verbosity=2)
