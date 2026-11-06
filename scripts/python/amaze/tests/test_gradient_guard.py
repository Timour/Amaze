"""Colors rides the family model; this pins that it does, plus the rules that are Colors' own."""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # BEFORE the app exists ▸p/first-app-picks-the-platform
from PySide6 import QtCore, QtGui, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from amaze.core import category                          # noqa: E402
from amaze.core import database                          # noqa: E402
from amaze.core import gradient_library                  # noqa: E402
from amaze.core import keyed_store                       # noqa: E402
from amaze.core import tile_icons                        # noqa: E402
from amaze.panel import sections                         # noqa: E402
from amaze.prefs import prefs                            # noqa: E402
from amaze.tests import test_support                     # noqa: E402

SCHEMA = database.SCHEMA_VERSION    # read from the module, so a fixture never silently tests the migration at the next bump


def _fixture_prefs(testcase, directory,
                   user="9f8e7d6c5b4a30211203a4b5c6d7e8f9"):  # minted shape - only uuid4().hex reads back as an owner
    """A real Prefs at the fixture dir: `.dir` keeps its trailing separator; `.path` spares settings."""
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
        test_support.reset_database_singletons()    # the connector is one instance per filename, process-wide; a stale one latches
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        self._write({"version": SCHEMA, "categories": ["Warm"],    # with an identity: the connector keys its whole union on it
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
        stat = os.stat(self.path)
        os.utime(self.path, ns=(stat.st_atime_ns,    # make the change unmistakable to an (mtime_ns, size) key, whatever the timer resolution
                                stat.st_mtime_ns + 5_000_000_000))

    def test_the_other_sessions_gradients_survive_our_save(self):
        """The connector three-way merges, like the other three databases: both sides survive."""
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

    def test_two_saves_in_a_row_work(self):
        """The baseline is refreshed after a write, or our own save looks like another edit on the next."""
        self.lib.add_user_gradient("first", "", {"values": [], "keys": []})
        self.lib.add_user_gradient("second", "", {"values": [], "keys": []})
        names = [g["name"] for g in self._read()["assets"]]
        self.assertIn(
            "second", names,
            "the second save was refused - the post-write baseline is "
            "not being refreshed")

    def test_a_missing_file_does_not_block_saving(self):
        """A missing file is not another session's edit; refusing there would block every save."""
        os.remove(self.path)
        self.lib.add_user_gradient("recreated", "",
                                   {"values": [], "keys": []})
        self.assertTrue(os.path.isfile(self.path),
                        "a missing file blocked the save entirely")

    def test_a_deleted_gradient_stays_deleted(self):
        """A delete must go through forget(): the connector unions, so an unmentioned row is kept."""
        row = _row_named(self, self.lib, "ours")
        self.lib.remove_rows([row])
        self.lib.add_user_gradient("kept", "", {"values": [], "keys": []})
        names = [g["name"] for g in self._read()["assets"]]
        self.assertIn("kept", names, "premise: the later save landed")
        self.assertNotIn(
            "ours", names,
            "the deleted palette came back on the next save - absence "
            "is not a delete through the connector, so it has to be "
            "said out loud")

    def test_a_saved_palette_lands_on_top_with_its_maps_in_step(self):
        """The newest palette is row 0, and every row's thumbnail key maps to the row it sits on."""
        self.lib.add_user_gradient("mine", "", {"values": [], "keys": []})
        rows = range(self.lib.rowCount())
        self.assertEqual(["mine", "ours"],
                         [self.lib.entry(row)["name"] for row in rows])
        self.assertEqual(self.lib.rowCount(), len(self.lib._mat_paths))
        self.assertEqual(
            list(rows),
            [self.lib._thumb_rows.get(self.lib._thumb_key(row)) for row in rows],
            "a palette saved on top left the rows below it mapped to "
            "their old places, so a repaint lands on the wrong tile")


class GradientTagsReachTheRowTest(unittest.TestCase):
    """A palette saved through the family dialog is tagged like any asset; the tag reaches the row."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_tags_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"version": SCHEMA, "categories": ["Warm"],
                       "assets": []}, fh)
        self.lib = gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))

    def _saved(self, name):
        """The row as it reached DISK, which is the only place a tag has to survive to."""
        with open(self.path, encoding="utf-8") as fh:
            for row in json.load(fh).get("assets", []):
                if row.get("name") == name:
                    return row
        self.fail("no palette named %r reached the file" % name)

    def test_the_tags_are_stored_on_the_saved_palette(self):
        """Through the family sanitizer: split, stripped and deduped; none given, none stored."""
        for name, tags, expected in (("mine", "warm,sunset", ["warm", "sunset"]),
                                     ("plain", None, []),
                                     ("dupes", "warm, warm ,, warm", ["warm"])):
            with self.subTest(name=name):
                given = {} if tags is None else {"tags": tags}
                self.lib.add_user_gradient(name, "Warm",
                                           {"values": [], "keys": []}, **given)
                self.assertEqual(
                    expected, self._saved(name).get("tags"),
                    "the tags the save dialog collected did not reach the "
                    "row as the family stores them")

    def test_a_reloaded_library_reads_them_back(self):
        self.lib.add_user_gradient("mine", "Warm",
                                   {"values": [], "keys": []},
                                   tags="warm,sunset")
        test_support.reset_database_singletons()
        again = gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))
        rows = [again._assets[r] for r in range(again.rowCount())
                if again._assets[r].name == "mine"]
        self.assertTrue(rows, "premise: the palette reloaded")
        self.assertEqual(["warm", "sunset"], list(rows[0].tags))


class GradientAbsenceAndShapeTest(unittest.TestCase):
    """The guards every database inherits, on this one, plus the seed marker honesty Colors owns."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_shape_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")

    def _library(self):
        return gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))

    def test_repair_and_the_loader_agree_that_the_file_was_here(self):
        """With the marker present and the file gone, Repair and the loader must both say it was here."""
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
        """Valid JSON of the wrong shape takes the parse-failure refusal: empty, latched, untouched."""
        for shape in ({"version": SCHEMA, "assets": "this is not a list"},
                      ["not", "an", "object"]):
            with self.subTest(shape=shape):
                test_support.reset_database_singletons()
                with open(self.path, "w", encoding="utf-8") as fh:
                    json.dump(shape, fh)
                lib = self._library()                       # must not raise
                self.assertTrue(getattr(lib, "_load_failed", False),
                                "a wrong-shaped file loaded as if it were "
                                "fine, so the next save would overwrite it")

    def test_the_sidebar_survives_the_same_file(self):
        """The sidebar reads the same file right after the library and must survive it too."""
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(["not", "an", "object"], fh)
        self._library()
        sidebar = gradient_library.GradientCategories(
            preferences=_fixture_prefs(self, self.dir))  # must not raise
        self.assertEqual(1, sidebar.rowCount(),
                         "the refused document should hold only `_All`")

    def test_the_seed_marker_is_withheld_when_the_save_did_not_land(self):
        """The seed marker is minted only for a save that landed, or the loader latches for the session."""
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


class GradientRowRideTest(unittest.TestCase):
    """A palette rides as a Material: `colors` and `ramp` pass through verbatim, nothing invented."""

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

    def test_a_loaded_row_rides_a_save_untouched_and_a_new_one_is_born_dated(self):
        """Colours and ramp verbatim, no invented date on a loaded row - but a new one is born now."""
        self.assertEqual(
            "", self.lib.assets[0].date,
            "a palette with no stored date claims it was created today")
        self.lib.add_user_gradient("mine", "", {"values": [], "keys": []})
        row = self._on_disk_row("ours")
        self.assertEqual([{"name": "red", "hex": "#ff0000"}],
                         row.get("colors"),
                         "the payload was dropped on the Material ride")
        self.assertEqual(["Constant"], row.get("ramp", {}).get("bases"))
        self.assertEqual("", row.get("date", ""),
                         "the fabricated date reached disk")
        self.assertNotEqual("", self._on_disk_row("mine").get("date", ""),
                            "a new palette should carry its birth date")

    def _pre_bump_library(self):
        """A v7 document with one id-less row beside a stamped one, at the literal old version on purpose."""
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"version": 7, "categories": [],
                       "assets": [{"name": "bare", "colors": []},
                                  {"name": "kept", "colors": [],
                                   "id": "keptid"}]}, fh)
        test_support.reset_database_singletons()

    def test_the_bump_mints_an_identity_only_where_there_is_none(self):
        """An id-less row re-mints on every load; a re-minted id orphans every note keyed to it."""
        self._pre_bump_library()
        gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))
        with open(self.path, encoding="utf-8") as fh:
            saved = json.load(fh)
        self.assertEqual(SCHEMA, saved.get("version"),
                         "the document did not reach the current schema")
        bare = [row["name"] for row in saved["assets"]
                if not str(row.get("id") or "")]
        self.assertEqual([], bare,
                         "%d row(s) still carry no identity" % len(bare))
        kept = {row["name"]: row.get("id") for row in saved["assets"]}
        self.assertEqual("keptid", kept.get("kept"),
                         "the migration overwrote an identity that was "
                         "already there")

    def test_a_minted_identity_is_stable_across_a_reload(self):
        """The whole point of writing it back: the id must not change on the next open."""
        self._pre_bump_library()
        first = gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))
        minted = first.tile_key(_row_named(self, first, "bare"))
        self.assertTrue(minted, "no identity was minted at all")
        test_support.reset_database_singletons()
        again = gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))
        self.assertEqual(
            minted, again.tile_key(_row_named(self, again, "bare")),
            "the identity did not survive the reload, so every launch "
            "keys the palette's notes and icon differently")


class GradientTileIconTest(unittest.TestCase):
    """A palette icon is stored, reaches the tile and is reversible; Customize writes no PNG for it."""

    def setUp(self):
        test_support.reset_database_singletons()
        keyed_store.release()
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

    def test_generic_shows_the_drop_and_preview_the_swatch(self):
        from PySide6 import QtCore
        index = self.lib.index(self.row, 0)
        painted = self.lib.data(index, QtCore.Qt.ItemDataRole.DecorationRole)
        self.lib.set_tile_icon(self.row, {"face": "generic"})
        drop = tile_icons.generic_image(gradient_library.GradientLibrary.TILE_FACE)
        self.assertEqual(drop, self.lib.data(index, QtCore.Qt.ItemDataRole.DecorationRole))
        self.lib.set_tile_icon(self.row, {"face": "preview"})
        self.assertEqual(painted, self.lib.data(index, QtCore.Qt.ItemDataRole.DecorationRole))
        self.assertNotEqual(drop, painted)

    def test_the_icon_survives_a_reload(self):
        """It must reach the store on disk; a spec kept in memory looks identical until a reopen."""
        self.assertEqual({}, self.lib.tile_icon(self.row))
        self.assertTrue(self.lib.set_tile_icon(
            self.row, {"name": "layers", "bg": "#4af2a1"}))
        self.assertEqual("layers", self.lib.tile_icon(self.row)["name"])
        test_support.reset_database_singletons()
        keyed_store.release()
        again = gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))
        row = _row_named(self, again, "ours")
        self.assertEqual("layers", again.tile_icon(row)["name"])

    def test_no_png_is_written(self):
        """The palette paints in memory; a PNG on disk would be a file no cleanup pass accounts for."""
        self.lib.set_tile_icon(self.row, {"name": "layers", "bg": "#4af2a1"})
        pngs = []
        for root, _dirs, names in os.walk(self.dir):
            pngs.extend(n for n in names if n.endswith(".png"))
        self.assertEqual([], pngs, "a palette icon wrote a PNG")

    def test_the_swatch_key_changes_with_the_icon(self):
        """Same palette, different picture: else the shared image cache serves whichever came first."""
        plain = self.lib._swatch_key(self.row)
        self.lib.set_tile_icon(self.row, {"name": "layers", "bg": "#4af2a1"})
        iconed = self.lib._swatch_key(self.row)
        self.assertNotEqual(plain, iconed)
        self.lib.set_tile_icon(self.row, {})
        self.assertEqual({}, self.lib.tile_icon(self.row))
        self.assertEqual(
            plain, self.lib._swatch_key(self.row),
            "clearing the icon did not return the palette to its own "
            "swatch key, so the cached icon image keeps painting")


class GradientCategoryColorTest(unittest.TestCase):
    """Category colours ride the shared Categories model, read per row, carried by rename/remove."""

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
        """The colour is set on the category and read per row, so a tile answers for its category."""
        self.sidebar.set_color("Warm", "#4af2a1")
        self.assertEqual("#4af2a1", self.lib.category_color(self.row))

    def test_a_rename_carries_the_colour(self):
        """A rename carries the colour; keyed by name, a lost colour reattaches if the name returns."""
        self.sidebar.set_color("Warm", "#4af2a1")
        self.lib.rename_category("Warm", "Hot")
        self.sidebar.rename_category("Warm", "Hot")
        self.assertTrue(self.lib.save())
        again = self._reload_sidebar()
        self.assertEqual("#4af2a1", again.color_of("Hot"))
        self.assertEqual("", again.color_of("Warm"))

    def test_removing_a_category_takes_its_colour(self):
        self.sidebar.set_color("Warm", "#4af2a1")
        self.lib.remove_category("Warm")
        self.sidebar.remove_category("Warm")
        self.assertTrue(self.lib.save())
        self.assertEqual("", self._reload_sidebar().color_of("Warm"))


class APaletteCategoryWithACommaStaysWholeTest(unittest.TestCase):
    """A palette dropped on a category whose name holds a comma is filed under the whole name."""

    NAME = "Wood, Oak"

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.dir = tempfile.mkdtemp(prefix="amaze_gcomma_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        with open(os.path.join(self.dir, "gradients.json"), "w", encoding="utf-8") as fh:
            json.dump({"version": SCHEMA, "categories": ["Warm", self.NAME],
                       "assets": [{"name": "ours", "categories": ["Warm"], "id": "ourscomma",
                                   "colors": [{"name": "red", "hex": "#ff0000"}]}]}, fh)
        self.lib = gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))

    def test_the_drop_door_files_it_under_the_whole_name(self):
        row = _row_named(self, self.lib, "ours")
        self.assertEqual(1, self.lib.set_user_category([row], self.NAME))
        self.assertEqual([self.NAME], self.lib.assets[row].categories,
                         "the drop split the category name at its comma")
        test_support.reset_database_singletons()
        again = gradient_library.GradientLibrary(preferences=_fixture_prefs(self, self.dir))
        self.assertEqual([self.NAME], again.assets[_row_named(self, again, "ours")].categories,
                         "the saved palette names another category")


def _curated_note_count() -> int:
    """How many curated combinations ship colour text, derived so a seed test cannot count nothing."""
    found = 0
    for curated in gradient_library.CURATED_SETS:
        path = gradient_library._def_path(curated["file"])
        if not path or not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8-sig") as handle:
            for combo in json.load(handle).get("combinations", []):
                if str(combo.get("note", "") or "").strip():
                    found += 1
    return found


class GradientSeedNoteTest(unittest.TestCase):
    """Curated colour text goes straight to the Comments page; the entry `note` is never written."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_seednote_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        self.prefs = _fixture_prefs(self, self.dir)

    def _seeded(self):
        lib = gradient_library.GradientLibrary(preferences=self.prefs)
        lib.seed_curated_palettes(
            gradient_library.GradientCategories(preferences=self.prefs))
        return lib

    def test_the_text_lands_on_the_page_and_never_on_the_entry(self):
        lib = self._seeded()
        from amaze.core import notes
        pages = [row for row in range(lib.rowCount())
                 if notes.note_for(
                     self.prefs,
                     notes.note_key("gradient", lib.tile_key(row))
                 ).get("items")]
        self.assertTrue(pages,
                        "no seeded palette carries its colour text, so "
                        "the seed dropped it")
        with open(self.path, encoding="utf-8") as fh:
            saved = json.load(fh)
        carried = [g["name"] for g in saved["assets"] if "note" in g]
        self.assertEqual([], carried,
                         "the retired field reached disk on %d rows"
                         % len(carried))


class GradientFirstOpenWriteCountTest(unittest.TestCase):
    """First open writes once, not per note: each write rotates a snapshot, pushing out history."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_writestorm_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "gradients.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(    # stamped ids and `_All` present, so neither the id persist nor its normalisation writes
                {"version": SCHEMA, "categories": ["_All"],
                 "assets": [{"name": "g%d" % i, "colors": [],
                             "id": "fixtureuid%02d" % i,
                             "note": "note %d" % i}
                            for i in range(12)]}, fh, indent=1)
        self.prefs = _fixture_prefs(self, self.dir)

    def _counted_writes(self):
        """Counts at hostos.write_json_atomic, where every engine write lands, not at a wrapper."""
        from amaze.helpers import hostos
        seen = []
        real = hostos.write_json_atomic

        def counting(path, *args, **kwargs):
            seen.append(os.path.basename(path))
            return real(path, *args, **kwargs)

        hostos.write_json_atomic = counting
        self.addCleanup(setattr, hostos, "write_json_atomic", real)
        return seen

    def test_the_whole_curated_seed_costs_one_notes_write(self):
        """39 pages, one write: a per-note write rotates a snapshot each time."""
        seen = self._counted_writes()
        lib = gradient_library.GradientLibrary(preferences=self.prefs)
        lib.seed_curated_palettes(
            gradient_library.GradientCategories(preferences=self.prefs))
        self.assertEqual(
            1, seen.count("notes.json"),
            "the seed wrote notes.json %d times; batching is what keeps "
            "the snapshot tier usable" % seen.count("notes.json"))
        from amaze.core import notes
        pages = sum(1 for row in range(lib.rowCount())
                    if notes.note_for(
                        self.prefs,
                        notes.note_key("gradient", lib.tile_key(row))
                    ).get("items"))
        self.assertEqual(_curated_note_count(), pages,
                         "%d of %d curated notes reached their page"
                         % (pages, _curated_note_count()))

    def test_stamped_rows_cost_no_identity_write(self):
        """Rows born stamped cost no write; counted, as an id afterwards cannot tell born from backfilled."""
        seen = self._counted_writes()
        gradient_library.GradientLibrary(preferences=self.prefs)
        self.assertLessEqual(
            seen.count("gradients.json"), 1,
            "first open wrote gradients.json %d times; the note sweep "
            "is one write and the identity persist should add none"
            % seen.count("gradients.json"))


class GradientTileNameTest(unittest.TestCase):
    """set_tile_name is the inherited rename path: narrow, persisted, a no-op on blank."""

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
    """A bad row is skipped and the good rows kept; one junk entry does not latch the library."""

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

    def test_the_good_rows_around_it_still_load(self):
        """Skip the bad row, keep the library - the connector's own merge policy, applied here."""
        good = {"name": "Warm", "colors": [], "id": "warmid"}
        self._write({"version": SCHEMA, "assets": [good, 42, None, "nope"],
                     "categories": []})
        lib = self._library()                       # must not raise
        self.assertEqual(
            ["Warm"],
            [lib.entry(r).get("name") for r in range(lib.rowCount())],
            "a file with junk rows lost its good gradients, or kept the junk")
        self.assertFalse(getattr(lib, "_load_failed", True),
                         "one junk row latched the whole library "
                         "read-only for the session")


class TwoRampsWithOneSetOfColoursDoNotShareATile(unittest.TestCase):
    """The swatch key hashes hexes, ramp bases and stop positions, or moved colours share a tile."""

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
        """An unchanged palette keeps its image: the key is the content, never the row number."""
        for keys_b, shared in (([0.0, 0.2], False), ([0.0, 1.0], True)):
            with self.subTest(keys_b=keys_b):
                test_support.reset_database_singletons()
                lib = self._library_with([0.0, 1.0], keys_b)
                self.assertEqual(
                    shared, lib._swatch_key(0) == lib._swatch_key(1),
                    "two ramps share a cache slot only when their colours "
                    "sit in the same places")


class TheColorsProxyIsTheFamilys(unittest.TestCase):
    """The family proxy plus Colors' own palette-size filter and a search reaching colour names."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_proxy_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        with open(os.path.join(self.dir, "gradients.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"version": SCHEMA, "categories": ["_All", "Warm"],
                       "assets": [
                {"id": "a", "name": "Sunrise", "categories": ["Warm"],
                 "colors": [{"name": "crimson", "hex": "#dc143c"},
                            {"name": "gold", "hex": "#ffd700"}]},
                {"id": "b", "name": "Marine", "categories": [],
                 "colors": [{"name": "teal", "hex": "#008080"}]},
            ]}, fh)
        self.model = gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))
        self.proxy = gradient_library.GradientFilterProxyModel()
        self.proxy.setSourceModel(self.model)

    def _shown(self):
        return sorted(
            self.proxy.data(self.proxy.index(row, 0),
                            QtCore.Qt.ItemDataRole.DisplayRole)
            for row in range(self.proxy.rowCount()))

    def test_the_family_category_filter_narrows_the_grid(self):
        self.proxy.setFilter(self.model.CategoryRole, "Warm")
        self.assertEqual(["Sunrise"], self._shown())
        self.proxy.setFilter(self.model.CategoryRole, "")
        self.assertEqual(["Marine", "Sunrise"], self._shown())

    def test_the_name_search_also_matches_a_colour_name(self):
        """A palette is found by what is inside it, which a plain family name filter would lose."""
        self.proxy.setFilter(QtCore.Qt.ItemDataRole.DisplayRole, "teal")
        self.assertEqual(
            ["Marine"], self._shown(),
            "searching a colour name no longer finds its palette")
        self.proxy.setFilter(QtCore.Qt.ItemDataRole.DisplayRole, "sunri")
        self.assertEqual(["Sunrise"], self._shown(),
                         "the ordinary name search broke in the fold")

    def test_the_size_filter_reads_its_range(self):
        self.proxy.set_size_filter((2, None))
        self.assertEqual(["Sunrise"], self._shown())
        self.proxy.set_size_filter((1, 1))
        self.assertEqual(["Marine"], self._shown())
        self.proxy.set_size_filter(None)
        self.assertEqual(["Marine", "Sunrise"], self._shown())


class AColourStarSurvivesAReloadTest(unittest.TestCase):
    """Colors stars go through the one favourites store, tagged by owner; the record field is dead."""

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

    def _library(self, user="8a7b6c5d4e3f20110213f4e5d6c7b8a9"):  # minted shape, as in _fixture_prefs
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
        lib.toggle_fav(_row_named(self, lib, "warm"))
        row = _row_named(self, lib, "warm")
        self.assertTrue(lib.data(lib.index(row, 0), lib.FavoriteRole),
                        "the toggle did not light the star it just set")
        lib.save()    # the shared record gains nothing on disk, or the star is everyone's again
        self.assertFalse(
            any("favorite" in row for row in self._disk_rows()
                if isinstance(row, dict)),
            "the star reached gradients.json - the shared document "
            "carries per-user state again")
        test_support.reset_database_singletons()    # a fresh session reads it back out of the library store
        keyed_store.release()
        again = self._library()
        arow = _row_named(self, again, "warm")
        self.assertTrue(
            again.data(again.index(arow, 0), again.FavoriteRole),
            "the star did not survive a reload through the store")

    def test_the_step_takes_a_star_off_a_version_5_document(self):
        """The v5 to v6 step strips stars from the shared document, where nothing reads them."""
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
            lib.data(lib.index(row, 0), lib.FavoriteRole),
            "a stripped record star still reads as a favourite - the "
            "read is answering the record, not the store")

    def test_no_user_picked_means_no_star_and_no_write(self):
        self._one_warm_palette()
        lib = self._library(user="")
        lib.toggle_fav(_row_named(self, lib, "warm"))
        urow = _row_named(self, lib, "warm")
        self.assertFalse(
            lib.data(lib.index(urow, 0), lib.FavoriteRole),
            "a machine with nobody picked lit a star - the store filed "
            "it under a blank tag, which is an ABSENT user, not a "
            "shared one")
        self.assertFalse(
            os.path.exists(os.path.join(self.dir, "favourites.json")),
            "a refused star still created the favourites store")


class ColorsHonourARefusedSave(unittest.TestCase):
    """A refused write is honoured in full: the row goes back, the delete is retracted, the user told."""

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

    def _stamp_of(self, asset_id):
        path = self.lib.asset_files(asset_id)["stamp"]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"id": asset_id, "name": "doomed"}, fh)
        return path

    def test_a_refused_delete_puts_the_palette_back(self):
        """Its stamp stays too, and no later save may commit the delete the list declined."""
        from unittest.mock import patch

        stamp = self._stamp_of("doomeduid")
        row = self._row_named("doomed")
        self.assertGreaterEqual(row, 0, "premise: the fixture loaded")
        with patch.object(database.DatabaseConnector, "save",
                          return_value=False):
            self.lib.remove_rows([row])

        self.assertIn("doomed", self._on_disk_names(),
                      "premise: the refusal kept it on disk")
        self.assertGreaterEqual(
            self._row_named("doomed"), 0,
            "the palette left the grid while gradients.json still "
            "listed it - the delete looked done and was not")
        self.assertTrue(os.path.exists(stamp),
                        "a delete the list refused took the stamp anyway")
        self.lib.add_user_gradient("later", "", {"values": [], "keys": []})    # anything at all that writes the file afterwards
        self.assertIn(
            "doomed", self._on_disk_names(),
            "the declined delete was committed by an unrelated save")

    def test_a_refused_add_leaves_no_palette_on_screen_or_in_the_next_save(self):
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
        self.lib.add_user_gradient("later", "", {"values": [], "keys": []})    # anything at all that writes the file afterwards
        self.assertNotIn(
            "ghost", self._on_disk_names(),
            "the refused palette reached disk with an unrelated save")

    def test_a_delete_removes_the_palette_and_its_stamp(self):
        """A stamp no list claims is what Repair rebuilds from, so a deleted palette takes its own."""
        stamp = self._stamp_of("doomeduid")
        self.lib.remove_rows([self._row_named("doomed")])
        self.assertEqual(-1, self._row_named("doomed"))
        self.assertNotIn("doomed", self._on_disk_names())
        self.assertFalse(os.path.exists(stamp),
                         "the deleted palette's stamp stayed in the asset folder")

    def test_a_refused_delete_is_not_put_into_another_library(self):
        """Another pane's switch moved the shared connector, so the take-back must not write to it."""
        other = tempfile.mkdtemp(prefix="amaze_grad_other_")
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        other_path = os.path.join(other, "gradients.json")
        with open(other_path, "w", encoding="utf-8") as fh:
            json.dump({"version": SCHEMA, "categories": ["_All"],
                       "assets": [{"name": "theirs", "id": "theirsuid",
                                   "colors": []}]}, fh, indent=1)
        connector = database.DatabaseConnector(self.lib.DB_FILENAME)
        connector.reload_with_path(other + os.sep)

        self.lib.remove_rows([self._row_named("doomed")])

        self.assertGreaterEqual(
            self._row_named("doomed"), 0,
            "premise: the refused delete put the palette back on screen")
        self.assertNotIn(
            "doomeduid", [r.get("id") for r in connector._data["assets"]],
            "the refused delete put the palette into the OTHER library's "
            "document - that library's next save writes it there")
        self.assertTrue(connector.save(), "premise: the other library saves")
        with open(other_path, encoding="utf-8") as fh:
            names = [r.get("name") for r in json.load(fh)["assets"]]
        self.assertNotIn("doomed", names,
                         "a palette from one library landed in another")


class ColorsHandOverWhatTheMergeAdopted(unittest.TestCase):
    """A row the merge adopted reaches the model: take_adopted() drains after every save."""

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
    """A peer's category and its colour must survive the save AFTER the merge."""

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
        self.assertEqual(
            "#7b5230",
            self._on_disk().get("category_colors", {}).get("Bronze"),
            "the peer's category colour was written out of existence - "
            "the colour table is a detached dict rebuilt on save")


class TheColorsSidebarIsTheSharedModel(unittest.TestCase):
    """The Colors sidebar is a category.Categories subclass, as Cop and Code, not a second model."""

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

    def test_the_All_row_is_pinned_first_and_a_row_answers_its_stored_name(self):
        sidebar = self._sidebar()
        self.assertEqual(
            "_All",
            sidebar.data(sidebar.index(0, 0), sidebar.CatSortRole),
            "row 0 is not the everything-marker, so the section's "
            "sidebar_key would read a category as All")
        found = [sidebar.data(sidebar.index(row, 0), sidebar.CatSortRole)
                 for row in range(sidebar.rowCount())]
        self.assertIn("Warm", found,
                      "the sidebar cannot name its own category, so a "
                      "click filters the grid to nothing")

    def test_a_new_category_reaches_the_sidebar_through_its_insert(self):
        """The save door files a palette, then hands its category to `check_add_category`."""
        shared = _fixture_prefs(self, self.dir)
        lib = gradient_library.GradientLibrary(preferences=shared)
        sidebar = gradient_library.GradientCategories(preferences=shared)
        told = []
        sidebar.rowsInserted.connect(
            lambda *_args: told.append(sidebar.rowCount()))
        lib.add_user_gradient("new", "Spring",
                              {"values": [[0.1, 0.2, 0.3]], "keys": [0.0]})
        sidebar.check_add_category("Spring")
        self.assertEqual([4], told,
                         "the sidebar gained a row it was never told about")
        self.assertEqual(
            "Spring", sidebar.data(sidebar.index(3, 0), sidebar.CatSortRole))

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
    """Colors inherits the shared role numbers; this pins the two facts left that are its own."""

    def test_no_two_roles_share_a_number(self):
        """No collision: data() answers whichever branch it tests first, so one field would return another."""
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
        """257 is matched with `for elem in data`, so a bare string would match per CHARACTER."""
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
    """Derived: every panel call on gradient_categories_model must exist, not a hand-kept list."""

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

    def test_the_panel_calls_nothing_the_colors_models_lack(self):
        """A caller left behind by a deleted method is a traceback after a real gesture."""
        for attribute, model in (
                ("gradient_categories_model", gradient_library.GradientCategories),
                ("gradient_model", gradient_library.GradientLibrary)):
            with self.subTest(attribute):
                calls = self._calls_on(attribute)
                self.assertTrue(
                    calls,
                    "found no calls at all - the walker stopped matching, "
                    "which would make this guard silently vacuous")
                missing = {method: sites for method, sites in calls.items()
                           if not hasattr(model, method)}
                self.assertEqual(
                    {}, missing,
                    "the panel calls these on %s and it does not have "
                    "them: %s" % (model.__name__, missing))


class TheAllMarkerIsNotChurnedOnEverySave(unittest.TestCase):
    """`_All` stays stored and the view filters it; stripping it costs a rewrite on the next launch."""

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

    def test_neither_marker_is_offered_as_a_category(self):
        """`_All`, or a plain All a merge left in memory or a hand edit left on disk."""
        self.lib._data["categories"].append("All")    # as a merge of another machine's list can leave it
        self.assertEqual(["Warm"], self.lib.user_categories(),
                         "the save dialog offers a marker as a category to file under")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"categories": ["_All", "All", "Warm"],
                       "assets": []}, fh, indent=1)
        test_support.reset_database_singletons()
        lib = gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))
        self.assertEqual(["Warm"], lib.user_categories(),
                         "the save dialog offers All as a category to file under")


class TheGradientEntryIsResolvedOnce(unittest.TestCase):
    """Every Colors door reaches its entry through `_entry_at`, so no door loses the shared guard."""

    def test_no_door_walks_the_proxy_for_itself(self):
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(sections))
        doors = [scope for klass in ast.walk(tree)
                 if isinstance(klass, ast.ClassDef) and klass.name == "GradientSection"
                 for scope in klass.body if isinstance(scope, ast.FunctionDef)]
        self.assertTrue(doors, "premise: the scan reads GradientSection")
        found = sorted(scope.name for scope in doors if scope.name != "_entry_at"
                       and any(isinstance(n, ast.Attribute) and n.attr == "mapToSource"
                               for n in ast.walk(scope)))
        self.assertEqual([], found, "a Colors door resolves its own entry, not via _entry_at")

    def test_an_index_the_proxy_has_dropped_answers_no_entry(self):
        """The guard `_entry_at` owns for every door: an unmappable index is no entry, never row -1's."""
        section = sections.GradientSection.__new__(sections.GradientSection)
        self.assertIsNone(sections.GradientSection._entry_at(section, None))


class ARampHelperIsTotal(unittest.TestCase):
    """`hou.Ramp` raises `InvalidSize` on mismatch, goes float when empty. ▸r/ramp-and-walk-edges"""

    def setUp(self):
        import hou
        from amaze.helpers import helpers
        self.hou = hou
        self.helpers = helpers

    def test_both_builders_give_an_empty_palette_one_colour_key(self):
        """They disagreed: one raised where the other returned black."""
        stepped = self.helpers.build_stepped_ramp([])
        self.assertTrue(stepped.isColor())
        self.assertEqual([0.0], list(stepped.keys()))
        basis = self.helpers.build_basis_ramp([], "Linear")
        self.assertEqual(len(basis.keys()), len(stepped.keys()))
        self.assertTrue(basis.isColor())

    def test_mismatched_keys_and_values_are_truncated_not_fatal(self):
        for data in ({},    # keyless: an empty hou.Ramp is a FLOAT ramp, silently wrong on a colour parm
                     {"bases": ["Linear"], "values": [[1, 0, 0]]},
                     {"bases": ["Linear"], "keys": [0.0]},
                     {"bases": [], "keys": [0.0, 1.0], "values": [[1, 0, 0]]}):
            ramp = self.helpers.data_to_ramp(data)
            self.assertTrue(ramp.isColor(), data)
            self.assertEqual(len(ramp.keys()), len(ramp.values()), data)

    def test_a_real_gradient_still_round_trips_exactly(self):
        """The degrading must not cost the ordinary case."""
        source = self.hou.Ramp(
            [self.hou.rampBasis.Linear] * 3, [0.0, 0.5, 1.0],
            [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)])
        back = self.helpers.data_to_ramp(self.helpers.ramp_to_data(source))
        self.assertEqual(list(source.keys()), list(back.keys()))
        self.assertEqual([list(v) for v in source.values()],
                         [list(v) for v in back.values()])

    def test_the_menu_offers_every_basis_the_reader_knows_in_order(self):
        self.assertEqual(
            ("Constant", "Linear", "CatmullRom", "MonotoneCubic",
             "Bezier", "BSpline", "Hermite"), self.helpers.RAMP_BASES)
        for name in self.helpers.RAMP_BASES:
            ramp = self.helpers.build_basis_ramp(["#ff0000", "#0000ff"], name)
            self.assertEqual(name, self.helpers.ramp_to_data(ramp)["bases"][0],
                             "the menu offers a basis the reader cannot name")


class TheSwatchPainterIsTotal(unittest.TestCase):
    """It paints inside `data()`, so a palette `data_to_ramp` survives paints. ▸r/ramp-and-walk-edges"""

    SIZE = gradient_library.THUMB_SIZE

    def _painted(self, colors, ramp):
        try:
            image = gradient_library.paint_swatch(colors, ramp)
        except Exception as exc:                          # noqa: BLE001
            self.fail("the swatch raised %s: %s - a blank tile and a traceback per repaint"
                      % (type(exc).__name__, exc))
        self.assertEqual((self.SIZE, self.SIZE), (image.width(), image.height()))
        return image

    def _at(self, image, x, y):
        return image.pixelColor(int(x * self.SIZE), int(y * self.SIZE))

    def test_keys_shorter_than_values_paint_the_width_both_hold(self):
        image = self._painted([], {"keys": [0.0], "values": [[1, 0, 0], [0, 1, 0]]})
        self.assertGreater(self._at(image, 0.5, 0.5).red(), 200)

    def test_a_value_with_two_channels_is_left_out(self):
        image = self._painted([], {"keys": [0.0, 1.0], "values": [[1, 0], [0, 1, 0]],
                                   "bases": ["Linear", "Linear"]})
        self.assertGreater(self._at(image, 0.5, 0.5).green(), 200)
        stepped = self._painted([], {"keys": [0.0, 0.5], "values": [[1, 0, 0], [0, 1]],
                                     "bases": ["Constant", "Constant"]})
        self.assertGreater(self._at(stepped, 0.25, 0.5).red(), 200)
        self.assertEqual(QtGui.QColor(gradient_library.EMPTY_SWATCH),
                         self._at(stepped, 0.75, 0.5),
                         "the band it left out is not the empty swatch's colour")

    def test_a_colour_with_no_hex_still_paints_the_others(self):
        image = self._painted([{"name": "red"}, "#00ff00", {"hex": "#0000ff"}], {})
        self.assertGreater(self._at(image, 0.5, 0.85).blue(), 200)
        empty = QtGui.QColor(gradient_library.EMPTY_SWATCH)
        self.assertEqual([empty, empty], [self._at(image, 0.5, y) for y in (0.15, 0.5)],
                         "a band with no readable hex was painted, not left empty")


class TheNodeWalkIsNotRecursive(unittest.TestCase):
    """Recursion per node hits Python's limit; the visited set bounds re-walks. ▸r/ramp-and-walk-edges"""

    def setUp(self):
        import hou
        from amaze.helpers import helpers
        self.helpers = helpers
        self.geo = hou.node("/obj").createNode("geo")
        self.addCleanup(self.geo.destroy)

    def _chain(self, length):
        previous = self.geo.createNode("null", "n0")
        for index in range(1, length):
            node = self.geo.createNode("null", "n%d" % index)
            node.setInput(0, previous)
            previous = node
        return previous

    def test_a_long_chain_walks_and_a_diamond_is_visited_once(self):
        """A diamond was re-walked once per path, exponentially, before the visited set."""
        deep = self._chain(1400)      # comfortably past the 1000-frame default
        walked = self.helpers.get_connected_input_nodes([deep], [])
        self.assertEqual(1400, len(walked))
        top = self.geo.createNode("null", "top")
        left = self.geo.createNode("null", "left")
        right = self.geo.createNode("null", "right")
        merge = self.geo.createNode("merge", "merge")
        left.setInput(0, top)
        right.setInput(0, top)
        merge.setInput(0, left)
        merge.setInput(1, right)

        walked = self.helpers.get_connected_input_nodes([merge], [])
        paths = [n.path() for n in walked]
        self.assertEqual(len(paths), len(set(paths)),
                         "a node was collected twice: %s" % paths)
        self.assertIn(top.path(), paths)


if __name__ == "__main__":
    unittest.main(verbosity=2)
