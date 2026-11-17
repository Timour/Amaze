"""Colors uses the family model; these tests check that, plus the rules that are Colors' own."""

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
from amaze.core import gradient_library                  # noqa: E402
from amaze.core import library_db                        # noqa: E402
from amaze.core import library_files                     # noqa: E402
from amaze.core import tile_icons                        # noqa: E402
from amaze.panel import sections                         # noqa: E402
from amaze.prefs import prefs                            # noqa: E402
from amaze.tests import test_support                     # noqa: E402

COLORS = library_files.COLORS


def _colors_document(document: dict) -> dict:
    """A {categories: [...], assets: [...]} payload as colors.json holds it: rows and categories keyed."""
    order = [name for name in document.get("categories") or []
             if isinstance(name, str) and name.lstrip("_") != "All"]
    rows = {}
    for row in document.get("assets") or []:
        if isinstance(row, dict):
            rows[str(row.get("id") or row.get("name"))] = dict(row)
    for row in rows.values():
        order.extend(name for name in row.get("categories") or [] if name not in order)
    return {"assets": rows,
            "categories": {name: {"order": at} for at, name in enumerate(order)},
            "comments": {}, "icons": {}, "favorites": {}}


def _lay(path: str, document: dict) -> None:
    """colors.json at `path`, written from the payload as another session would leave it."""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(_colors_document(document), fh, indent=1)


def _rows_on_disk(path: str) -> list:
    """The palette rows colors.json holds, in its order."""
    with open(path, encoding="utf-8") as fh:
        return list((json.load(fh).get("assets") or {}).values())


def _fixture_prefs(testcase, directory,
                   user="9f8e7d6c5b4a30211203a4b5c6d7e8f9"):  # uuid4().hex format - only that format is read back as an owner
    """A real Prefs at the fixture dir: `.dir` ends in a separator; `.path` is a temp dir."""
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
        test_support.reset_database_singletons()    # the connector is one instance per filename, process-wide; a stale one stays failed
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, COLORS)
        self._write({"categories": ["Warm"],
                     "assets": [{"name": "ours", "id": "oursuid",
                                 "colors": []}]})
        self.lib = gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))

    def _write(self, data):
        _lay(self.path, data)

    def _names(self):
        return [row["name"] for row in _rows_on_disk(self.path)]

    def _touch_from_another_session(self):
        """Another writer adds two palettes after we loaded the file."""
        self._write({"categories": ["Warm", "Theirs"],
                     "assets": [{"name": "ours", "id": "oursuid", "colors": []},
                                {"name": "theirs", "colors": [],
                                 "id": "theirsuid1"},
                                {"name": "theirs2", "colors": [],
                                 "id": "theirsuid2"}]})

    def test_the_other_sessions_gradients_survive_our_save(self):
        """The database does a three-way merge, like every other one: both sides' rows are kept."""
        self._touch_from_another_session()
        self.lib.add_user_gradient("mine", "", {"values": [], "keys": []})
        names = self._names()
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
        names = self._names()
        self.assertIn(
            "second", names,
            "the second save failed - the post-write baseline is "
            "not being refreshed")

    def test_a_missing_file_does_not_block_saving(self):
        """A missing file is not another session's edit; failing there would block every save."""
        os.remove(self.path)
        self.lib.add_user_gradient("recreated", "",
                                   {"values": [], "keys": []})
        self.assertTrue(os.path.isfile(self.path),
                        "a missing file blocked the save entirely")

    def test_a_deleted_gradient_stays_deleted(self):
        """A delete must call forget(): the connector merges by union, so an omitted row is kept."""
        row = _row_named(self, self.lib, "ours")
        self.lib.remove_rows([row])
        self.lib.add_user_gradient("kept", "", {"values": [], "keys": []})
        names = self._names()
        self.assertIn("kept", names, "premise: the later save was written")
        self.assertNotIn(
            "ours", names,
            "the deleted palette came back on the next save - absence "
            "is not a delete through the connector, so it has to be "
            "passed to forget()")

    def test_a_saved_palette_lands_on_top_with_its_maps_in_step(self):
        """The newest palette is row 0, and every row's thumbnail key maps to its own row."""
        self.lib.add_user_gradient("mine", "", {"values": [], "keys": []})
        rows = range(self.lib.rowCount())
        self.assertEqual(["mine", "ours"],
                         [self.lib.entry(row)["name"] for row in rows])
        self.assertEqual(self.lib.rowCount(), len(self.lib._mat_paths))
        self.assertEqual(
            list(rows),
            [self.lib._thumb_rows.get(self.lib._thumb_key(row)) for row in rows],
            "a palette saved on top left the rows below it mapped to "
            "their old rows, so a repaint draws the wrong tile")


class GradientTagsReachTheRowTest(unittest.TestCase):
    """A palette saved through the family dialog is tagged like any asset, on its row."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_tags_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, COLORS)
        _lay(self.path, {"categories": ["Warm"], "assets": []})
        self.lib = gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))

    def _saved(self, name):
        """The row as written to DISK, the only place a tag must be kept."""
        for row in _rows_on_disk(self.path):
            if row.get("name") == name:
                return row
        self.fail("no palette named %r was written to the file" % name)

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
                    "the tags the save dialog collected were not stored on the "
                    "row the way the family stores them")

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
    """The checks every database inherits, on colors.json, plus the seed marker rule Colors has."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_shape_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, COLORS)
        self.addCleanup(library_db.release)

    def _library(self):
        return gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))

    def test_a_wrong_shaped_file_does_not_take_the_panel_down(self):
        """Valid JSON of the wrong shape is a parse failure: empty, marked failed, never written."""
        for shape in ({"assets": "this is not a table"},
                      ["not", "an", "object"]):
            with self.subTest(shape=shape):
                test_support.reset_database_singletons()
                library_db.release()
                with open(self.path, "w", encoding="utf-8") as fh:
                    json.dump(shape, fh)
                lib = self._library()                       # must not raise
                self.assertTrue(getattr(lib, "_load_failed", False),
                                "a wrong-shaped file loaded as if it were "
                                "fine, so the next save would overwrite it")
                lib.add_user_gradient("refused", "", {"values": [], "keys": []})
                library_db.flush()
                with open(self.path, encoding="utf-8") as fh:
                    self.assertEqual(shape, json.load(fh), "the wrong-shaped file was written over")

    def test_the_sidebar_survives_the_same_file(self):
        """The sidebar reads the same file right after the library and must not raise either."""
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(["not", "an", "object"], fh)
        self._library()
        sidebar = gradient_library.GradientCategories(
            preferences=_fixture_prefs(self, self.dir))  # must not raise
        self.assertEqual(1, sidebar.rowCount(),
                         "the unreadable document should hold only `_All`")

    def test_the_seed_marker_is_withheld_when_the_save_did_not_land(self):
        """The seed mark is written only if the seed's save succeeds, else seeding never reruns."""
        from amaze.core import library_settings
        prefs_ = _fixture_prefs(self, self.dir)
        lib = gradient_library.GradientLibrary(preferences=prefs_)
        with test_support.full_disk_for(self.path):
            lib.seed_curated_palettes(gradient_library.GradientCategories(preferences=prefs_))
        self.assertFalse(os.path.exists(self.path), "premise: the seed was not written")
        library_db.release()
        self.assertFalse(
            library_settings.marked(_fixture_prefs(self, self.dir), lib._SEED_MARK),
            "the seed wrote its permanent marker for a failed save")


class GradientRowRideTest(unittest.TestCase):
    """A palette is stored as a Material: `colors` and `ramp` are kept verbatim, nothing added."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_ride_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, COLORS)
        _lay(self.path, {"categories": ["Warm"],
                         "assets": [{"name": "ours", "id": "oursuid",
                                     "categories": ["Warm"],
                                     "colors": [{"name": "red",
                                                 "hex": "#ff0000"}],
                                     "ramp": {"keys": [0.0],
                                              "values": [[1, 0, 0]],
                                              "bases": ["Constant"]}}]})
        self.lib = gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))

    def _on_disk_row(self, name):
        for row in _rows_on_disk(self.path):
            if isinstance(row, dict) and row.get("name") == name:
                return row
        self.fail("no row named %r on disk" % name)

    def test_a_loaded_row_rides_a_save_untouched_and_a_new_one_is_born_dated(self):
        """Colours and ramp verbatim, no invented date on a loaded row; a new row is dated now."""
        self.assertEqual(
            "", self.lib.assets[0].date,
            "a palette with no stored date shows today as its creation date")
        self.lib.add_user_gradient("mine", "", {"values": [], "keys": []})
        row = self._on_disk_row("ours")
        self.assertEqual([{"name": "red", "hex": "#ff0000"}],
                         row.get("colors"),
                         "the payload was dropped when stored as a Material")
        self.assertEqual(["Constant"], row.get("ramp", {}).get("bases"))
        self.assertEqual("", row.get("date", ""),
                         "the invented date was written to disk")
        self.assertNotEqual("", self._on_disk_row("mine").get("date", ""),
                            "a new palette should have its creation date")

class GradientTileIconTest(unittest.TestCase):
    """A palette icon is stored, reaches the tile and is reversible; Customize writes no PNG for it."""

    def setUp(self):
        test_support.reset_database_singletons()
        library_db.release()
        self.dir = tempfile.mkdtemp(prefix="amaze_gicon_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, COLORS)
        _lay(self.path, {"categories": ["Warm"], "assets": [
            {"name": "ours", "categories": ["Warm"], "id": "oursicon",
             "colors": [{"name": "red", "hex": "#ff0000"},
                        {"name": "blue", "hex": "#0000ff"}]}]})
        self.prefs = _fixture_prefs(self, self.dir)
        self.lib = gradient_library.GradientLibrary(preferences=self.prefs)
        self.row = _row_named(self, self.lib, "ours")

    def test_generic_shows_the_drop_and_image_the_swatch(self):
        from PySide6 import QtCore
        index = self.lib.index(self.row, 0)
        painted = self.lib.data(index, QtCore.Qt.ItemDataRole.DecorationRole)
        self.lib.set_tile_icon(self.row, {"face": "generic"})
        drop = tile_icons.generic_image(gradient_library.GradientLibrary.TILE_FACE)
        self.assertEqual(drop, self.lib.data(index, QtCore.Qt.ItemDataRole.DecorationRole))
        self.lib.set_tile_icon(self.row, {"face": "image"})    # no capture: the painted swatch
        self.assertEqual(painted, self.lib.data(index, QtCore.Qt.ItemDataRole.DecorationRole))
        self.assertNotEqual(drop, painted)

    def test_the_icon_survives_a_reload(self):
        """It must reach the store on disk; a spec kept in memory looks identical until a reopen."""
        self.assertEqual({}, self.lib.tile_icon(self.row))
        self.assertTrue(self.lib.set_tile_icon(
            self.row, {"name": "layers", "bg": "#4af2a1"}))
        self.assertEqual("layers", self.lib.tile_icon(self.row)["name"])
        test_support.reset_database_singletons()
        library_db.release()
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
        """Same palette, new icon: else the shared image cache returns the image cached first."""
        plain = self.lib._swatch_key(self.row)
        self.lib.set_tile_icon(self.row, {"name": "layers", "bg": "#4af2a1"})
        iconed = self.lib._swatch_key(self.row)
        self.assertNotEqual(plain, iconed)
        self.lib.set_tile_icon(self.row, {})
        self.assertEqual({}, self.lib.tile_icon(self.row))
        self.assertEqual(
            plain, self.lib._swatch_key(self.row),
            "clearing the icon did not return the palette to its own "
            "swatch key, so the cached icon image is still drawn")


class GradientCategoryColorTest(unittest.TestCase):
    """Category colours are in the shared Categories model, read per row, kept by rename/remove."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_gcol_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, COLORS)
        _lay(self.path, {"categories": ["Warm"], "assets": [
            {"name": "ours", "categories": ["Warm"], "id": "ourscolor",
             "colors": [{"name": "red", "hex": "#ff0000"}]}]})
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
        """Set on the category, read per row: a tile returns its category's colour."""
        self.sidebar.set_color("Warm", "#4af2a1")
        self.assertEqual("#4af2a1", self.lib.category_color(self.row))

    def test_a_rename_carries_the_colour(self):
        """A rename moves the colour; keyed by name, an old colour returns if the name is reused."""
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
        _lay(os.path.join(self.dir, COLORS),
             {"categories": ["Warm", self.NAME],
              "assets": [{"name": "ours", "categories": ["Warm"], "id": "ourscomma",
                          "colors": [{"name": "red", "hex": "#ff0000"}]}]})
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
    """How many curated combinations ship colour text, counted so a seed test cannot count zero."""
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
        self.path = os.path.join(self.dir, COLORS)
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
                        "no seeded palette has its colour text, so "
                        "the seed dropped it")
        carried = [g["name"] for g in _rows_on_disk(self.path) if "note" in g]
        self.assertEqual([], carried,
                         "the retired `note` field was written on %d rows"
                         % len(carried))


class GradientFirstOpenWriteCountTest(unittest.TestCase):
    """First open writes once, not per note: each write rotates a backup and drops the oldest."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_writestorm_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, COLORS)
        _lay(self.path, {"categories": [],
                         "assets": [{"name": "g%d" % i, "colors": [],
                                     "id": "fixtureuid%02d" % i}
                                    for i in range(12)]})
        self.prefs = _fixture_prefs(self, self.dir)

    def _counted_writes(self):
        """Database files written, counted at `guard.Disk.write`, which every write goes through."""
        from unittest import mock
        from amaze.core import guard
        seen = []
        real = guard.Disk.write

        def counting(disk, path, data):
            if os.path.basename(os.path.dirname(path)) != guard.BACKUP_DIR:
                seen.append(os.path.basename(path).split(".json")[0] + ".json")
            return real(disk, path, data)

        patcher = mock.patch.object(guard.Disk, "write", counting)
        patcher.start()
        self.addCleanup(patcher.stop)
        return seen

    def test_the_whole_curated_seed_costs_one_notes_write(self):
        """39 pages, one write: a per-note write would make a backup each time."""
        from unittest import mock
        from amaze.core import notes
        seen = self._counted_writes()
        lib = gradient_library.GradientLibrary(preferences=self.prefs)
        during_pages = []
        real_set_notes = notes.set_notes

        def counted_set_notes(*args, **kwargs):
            before = seen.count(COLORS)
            answer = real_set_notes(*args, **kwargs)
            during_pages.append(seen.count(COLORS) - before)
            return answer

        timer = []
        library_db.set_scheduler(lambda: timer.append(1))    # as the panel does: a burst of writes is deferred
        self.addCleanup(library_db.drop_scheduler)
        with mock.patch.object(notes, "set_notes", counted_set_notes):
            lib.seed_curated_palettes(
                gradient_library.GradientCategories(preferences=self.prefs))
        library_db.flush()
        self.assertGreater(lib.rowCount(), 12, "premise: the seed ran")
        self.assertEqual([1], during_pages,
                         "the seed wrote its pages in %s writes; batching is what "
                         "keeps the backups usable" % during_pages)
        self.assertLessEqual(seen.count(COLORS), 3,
                             "the seed wrote colors.json %d times; the rows, the pages "
                             "and the categories once each" % seen.count(COLORS))
        from amaze.core import notes
        pages = sum(1 for row in range(lib.rowCount())
                    if notes.note_for(
                        self.prefs,
                        notes.note_key("gradient", lib.tile_key(row))
                    ).get("items"))
        self.assertEqual(_curated_note_count(), pages,
                         "%d of %d curated notes were written to their page"
                         % (pages, _curated_note_count()))

    def test_stamped_rows_cost_no_identity_write(self):
        """Rows with ids cost no write; counted, as an id cannot show whether it was backfilled."""
        seen = self._counted_writes()
        gradient_library.GradientLibrary(preferences=self.prefs)
        library_db.flush()
        self.assertEqual(
            0, seen.count(COLORS),
            "first open wrote colors.json %d times; opening a library "
            "that holds nothing to change writes nothing" % seen.count(COLORS))


class GradientTileNameTest(unittest.TestCase):
    """set_tile_name is the inherited rename path: narrow, persisted, a no-op on blank."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_gradname_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, COLORS)
        _lay(self.path, {"categories": [],
                         "assets": [{"name": "klee", "colors": [], "id": "kleeid"}]})
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
    """A bad row is skipped, good rows kept; one junk entry does not make the library read-only."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_rows_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, COLORS)

    def _write(self, payload):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def _library(self):
        return gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))

    def test_the_good_rows_around_it_still_load(self):
        """Skip the bad row, keep the library: one junk entry loses only that entry."""
        good = {"name": "Warm", "colors": [], "id": "warmid"}
        self._write({"assets": {"warmid": good, "n": 42, "none": None, "s": "nope"},
                     "categories": {}})
        lib = self._library()                       # must not raise
        self.assertEqual(
            ["Warm"],
            [lib.entry(r).get("name") for r in range(lib.rowCount())],
            "a file with junk rows lost its good gradients, or kept the junk")
        self.assertFalse(getattr(lib, "_load_failed", True),
                         "one junk row made the whole library "
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
        _lay(os.path.join(self.dir, COLORS),
             {"categories": [], "assets": [_row("a", keys_a), _row("b", keys_b)]})
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
                    "are at the same positions")


class TheColorsProxyIsTheFamilys(unittest.TestCase):
    """The family proxy plus Colors' own palette-size filter and a search reaching colour names."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_proxy_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        _lay(os.path.join(self.dir, COLORS), {"categories": ["Warm"], "assets": [
            {"id": "a", "name": "Sunrise", "categories": ["Warm"],
             "colors": [{"name": "crimson", "hex": "#dc143c"},
                        {"name": "gold", "hex": "#ffd700"}]},
            {"id": "b", "name": "Marine", "categories": [],
             "colors": [{"name": "teal", "hex": "#008080"}]},
        ]})
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
        """A palette is found by its colour names, which a plain family name filter would miss."""
        self.proxy.setFilter(QtCore.Qt.ItemDataRole.DisplayRole, "teal")
        self.assertEqual(
            ["Marine"], self._shown(),
            "searching a colour name no longer finds its palette")
        self.proxy.setFilter(QtCore.Qt.ItemDataRole.DisplayRole, "sunri")
        self.assertEqual(["Sunrise"], self._shown(),
                         "the ordinary name search broke in the shared proxy")

    def test_the_size_filter_reads_its_range(self):
        self.proxy.set_size_filter((2, None))
        self.assertEqual(["Sunrise"], self._shown())
        self.proxy.set_size_filter((1, 1))
        self.assertEqual(["Marine"], self._shown())
        self.proxy.set_size_filter(None)
        self.assertEqual(["Marine", "Sunrise"], self._shown())


class AColourStarSurvivesAReloadTest(unittest.TestCase):
    """Colors stars are in colors.json's stars section, per user; the row's own field is unused."""

    USER = "8a7b6c5d4e3f20110213f4e5d6c7b8a9"    # uuid4().hex format, as in _fixture_prefs

    def setUp(self):
        test_support.reset_database_singletons()
        library_db.release()
        self.addCleanup(library_db.release)
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_star_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, COLORS)

    def _library(self, user=USER):
        return gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir, user=user))

    def _one_warm_palette(self):
        _lay(self.path, {"categories": ["Warm"],
                         "assets": [{"name": "warm", "id": "warmid",
                                     "categories": ["Warm"], "colors": []}]})

    def _disk_rows(self):
        return _rows_on_disk(self.path)

    def _disk_stars(self):
        with open(self.path, encoding="utf-8") as fh:
            return json.load(fh).get("favorites", {})

    def test_a_star_lands_in_the_store_and_survives_a_reload(self):
        self._one_warm_palette()
        lib = self._library()
        lib.toggle_fav(_row_named(self, lib, "warm"))
        row = _row_named(self, lib, "warm")
        self.assertTrue(lib.data(lib.index(row, 0), lib.FavoriteRole),
                        "the toggle did not show the star it just set")
        lib.save()
        library_db.flush()
        self.assertFalse(
            any("favorite" in row for row in self._disk_rows()
                if isinstance(row, dict)),
            "the star was written to the shared row - the shared section "
            "holds per-user state again")
        self.assertEqual({self.USER: {"warmid": True}}, self._disk_stars())
        test_support.reset_database_singletons()    # a new session reads it back from the library
        library_db.release()
        again = self._library()
        arow = _row_named(self, again, "warm")
        self.assertTrue(
            again.data(again.index(arow, 0), again.FavoriteRole),
            "the star was lost on reload")
        other = self._library(user="1a2b3c4d5e6f70811213f4e5d6c7b8a9")
        self.assertFalse(
            other.data(other.index(_row_named(self, other, "warm"), 0), other.FavoriteRole),
            "one user's star showed for another user")

    def test_a_star_field_on_a_row_is_not_a_star(self):
        """Only the stars section is read; a favorite field left on a row is no one's star."""
        _lay(self.path, {"categories": ["Warm"],
                         "assets": [{"name": "warm", "id": "warmid",
                                     "categories": ["Warm"], "colors": [],
                                     "favorite": True}]})
        lib = self._library()
        row = _row_named(self, lib, "warm")
        self.assertFalse(
            lib.data(lib.index(row, 0), lib.FavoriteRole),
            "a row field still reads as a favourite - the read is "
            "reading the record, not the stars section")

    def test_no_user_picked_means_no_star_and_no_write(self):
        self._one_warm_palette()
        lib = self._library(user="")
        lib.toggle_fav(_row_named(self, lib, "warm"))
        urow = _row_named(self, lib, "warm")
        self.assertFalse(
            lib.data(lib.index(urow, 0), lib.FavoriteRole),
            "a machine with no user picked showed a star - the store saved "
            "it under a blank user, which is an ABSENT user, not a "
            "shared one")
        library_db.flush()
        self.assertEqual({}, self._disk_stars(), "a star with no user was still written to colors.json")


class ColorsHonourARefusedSave(unittest.TestCase):
    """A failed write is undone in full: the row restored, the delete undone, the user alerted."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_refuse_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, COLORS)
        _lay(self.path, {"categories": ["Warm"], "assets": [
            {"name": "keep", "id": "keepuid", "colors": []},
            {"name": "doomed", "id": "doomeduid", "colors": []}]})
        self.lib = gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))

    def _row_named(self, name):
        for row in range(self.lib.rowCount()):
            entry = self.lib.entry(row)
            if entry and entry.get("name") == name:
                return row
        return -1

    def _on_disk_names(self, path=None):
        return [r.get("name") for r in _rows_on_disk(path or self.path) if isinstance(r, dict)]

    def _stamp_of(self, asset_id):
        """The palette's one file, its captured picture in `colors/`; the row owns it."""
        path = self.lib.asset_files(asset_id).get("thumbnail")
        self.assertTrue(path, "premise: the palette owns its picture")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(b"\x89PNG\r\n")
        return path

    def test_a_refused_delete_puts_the_palette_back(self):
        """Its stamp file stays too, and no later save may commit the delete that failed."""
        stamp = self._stamp_of("doomeduid")
        row = self._row_named("doomed")
        self.assertGreaterEqual(row, 0, "premise: the fixture loaded")
        with test_support.full_disk_for(self.path):
            self.lib.remove_rows([row])
            library_db.flush()

        self.assertIn("doomed", self._on_disk_names(),
                      "premise: the failed write kept it on disk")
        self.assertGreaterEqual(
            self._row_named("doomed"), 0,
            "the palette left the grid while colors.json still "
            "listed it - the delete looked done and was not")
        self.assertTrue(os.path.exists(stamp),
                        "a failed delete removed the stamp anyway")
        self.lib.add_user_gradient("later", "", {"values": [], "keys": []})    # anything at all that writes the file afterwards
        self.assertIn(
            "doomed", self._on_disk_names(),
            "the failed delete was committed by an unrelated save")

    def test_a_refused_add_leaves_no_palette_on_screen_or_in_the_next_save(self):
        """An unreadable database accepts no palette: none on screen, none written later."""
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{damaged")
        test_support.reset_database_singletons()
        library_db.release()
        lib = gradient_library.GradientLibrary(preferences=_fixture_prefs(self, self.dir))
        before = lib.rowCount()
        lib.add_user_gradient("ghost", "", {"values": [], "keys": []})
        library_db.flush()
        self.assertEqual(
            before, lib.rowCount(),
            "a palette that never reached disk stayed in the grid, so "
            "it is gone at the next launch with no message")
        with open(self.path, encoding="utf-8") as fh:
            self.assertEqual("{damaged", fh.read(), "the rejected palette was written")

    def test_an_add_the_disk_refused_is_said_and_lands_at_the_next_save(self):
        """A full disk: an alert, the palette kept in memory, and the next save writes it."""
        from unittest import mock
        from amaze.core import debug
        with test_support.full_disk_for(self.path), \
                mock.patch.object(debug, "alert") as alert:
            self.lib.add_user_gradient("held", "", {"values": [], "keys": []})
            library_db.flush()
        self.assertTrue(alert.called, "a failed write raised no alert")
        self.assertNotIn("held", self._on_disk_names(), "premise: the disk write failed")
        self.assertGreaterEqual(self._row_named("held"), 0,
                                "the unsaved palette left the grid")
        self.lib.add_user_gradient("later", "", {"values": [], "keys": []})
        library_db.flush()
        self.assertIn("held", self._on_disk_names(),
                      "the palette that failed to write was lost instead of saved")

    def test_a_delete_removes_the_palette_and_its_stamp(self):
        """Repair rebuilds rows from unlisted stamps, so deleting a palette deletes its stamp."""
        stamp = self._stamp_of("doomeduid")
        self.lib.remove_rows([self._row_named("doomed")])
        self.assertEqual(-1, self._row_named("doomed"))
        self.assertNotIn("doomed", self._on_disk_names())
        self.assertFalse(os.path.exists(stamp),
                         "the deleted palette's stamp stayed in the asset folder")

    def test_a_refused_delete_is_not_put_into_another_library(self):
        """Another pane has another library open; restoring the row must not write into it."""
        other = tempfile.mkdtemp(prefix="amaze_grad_other_")
        self.addCleanup(shutil.rmtree, other, ignore_errors=True)
        other_path = os.path.join(other, COLORS)
        _lay(other_path, {"categories": [],
                          "assets": [{"name": "theirs", "id": "theirsuid", "colors": []}]})
        theirs = gradient_library.GradientLibrary(preferences=_fixture_prefs(self, other))

        with test_support.full_disk_for(self.path):
            self.lib.remove_rows([self._row_named("doomed")])

        self.assertGreaterEqual(
            self._row_named("doomed"), 0,
            "premise: the failed delete put the palette back on screen")
        self.assertNotIn(
            "doomeduid", [theirs.tile_key(row) for row in range(theirs.rowCount())],
            "the failed delete put the palette into the OTHER library")
        theirs.add_user_gradient("theirs2", "", {"values": [], "keys": []})
        library_db.flush()
        self.assertNotIn("doomed", self._on_disk_names(other_path),
                         "a palette from one library was written into another")
        self.assertIn("theirs2", self._on_disk_names(other_path), "premise: the other library saves")


class ColorsHandOverWhatTheMergeAdopted(unittest.TestCase):
    """A row the merge adopted reaches the model: take_adopted() runs after every save."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_adopt_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, COLORS)
        _lay(self.path, {"categories": ["Warm"],
                         "assets": [{"name": "ours", "id": "oursuid", "colors": []}]})
        from amaze.core import model_registry
        self.addCleanup(test_support.reset_database_singletons)
        self.lib = model_registry.models_for(_fixture_prefs(self, self.dir))["gradient_model"]

    def test_a_palette_the_other_mac_added_reaches_the_grid(self):
        with open(self.path, encoding="utf-8") as fh:
            document = json.load(fh)
        document["assets"]["theirsid"] = {"name": "from_theirs", "id": "theirsid",
                                          "colors": []}
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(document, fh, indent=1)

        # Any ordinary edit takes the merge path.
        self.lib.add_user_gradient("mine", "", {"values": [], "keys": []})

        names = [self.lib.entry(r).get("name")
                 for r in range(self.lib.rowCount())]
        self.assertIn(
            "from_theirs", names,
            "the merge adopted the row into colors.json and never "
            "passed it to the model, so the grid, the sidebar counts "
            "and the filter never saw it - and the next save rebuilds "
            "the list without it")


class ColorsHandOverWhatTheMergeAdoptedIntoCATEGORIES(unittest.TestCase):
    """Another session's category and its colour must be kept by the save AFTER the merge."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_cat_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, COLORS)
        document = _colors_document({"categories": ["Warm"],
                                     "assets": [{"name": "ours", "id": "oursid", "colors": []}]})
        document["categories"]["Warm"]["color"] = "#c08040"
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(document, fh, indent=1)
        self.lib = gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))

    def _peer_adds_a_category(self):
        document = self._on_disk()
        document["categories"]["Bronze"] = {"order": 1, "color": "#7b5230"}
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(document, fh, indent=1)

    def _on_disk(self):
        with open(self.path, encoding="utf-8") as fh:
            return json.load(fh)

    def test_a_peers_category_survives_the_SECOND_edit_too(self):
        self._peer_adds_a_category()
        # Edit one merges; edit two is the one that used to erase it.
        self.lib.add_user_gradient("mine", "", {"values": [], "keys": []})
        self.assertIn("Bronze", self._on_disk().get("categories", {}),
                      "the merge itself is broken - this test is about "
                      "the save AFTER the merge")
        self.lib.add_user_gradient("mine2", "", {"values": [], "keys": []})
        self.assertIn(
            "Bronze", self._on_disk().get("categories", {}),
            "the second Colors edit deleted the other machine's "
            "category - the model holds a detached copy of the "
            "category list")
        self.assertEqual(
            "#7b5230",
            self._on_disk()["categories"]["Bronze"].get("color"),
            "the other session's category colour was deleted - "
            "the colour table is a detached dict rebuilt on save")


class TheColorsSidebarIsTheSharedModel(unittest.TestCase):
    """The Colors sidebar is a category.Categories subclass, as Cop and Code, not a second model."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_side_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        _lay(os.path.join(self.dir, COLORS), {
            "categories": ["Warm", "Cool"],
            "assets": [{"id": "a", "name": "one", "categories": ["Warm"], "colors": []},
                       {"id": "b", "name": "two", "categories": ["Warm"], "colors": []}]})

    def _sidebar(self):
        return gradient_library.GradientCategories(
            preferences=_fixture_prefs(self, self.dir))

    def test_the_All_row_is_pinned_first_and_a_row_answers_its_stored_name(self):
        sidebar = self._sidebar()
        self.assertEqual(
            "_All",
            sidebar.data(sidebar.index(0, 0), sidebar.CatSortRole),
            "row 0 is not `_All`, so the section's "
            "sidebar_key would read a category as All")
        found = [sidebar.data(sidebar.index(row, 0), sidebar.CatSortRole)
                 for row in range(sidebar.rowCount())]
        self.assertIn("Warm", found,
                      "the sidebar cannot name its own category, so a "
                      "click filters the grid to nothing")

    def test_a_new_category_reaches_the_sidebar_through_its_insert(self):
        """`add_user_gradient` files a palette, then its category goes to `check_add_category`."""
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
                         "the sidebar gained a row without emitting rowsInserted")
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
    """Colors inherits the shared role numbers; these tests check the two rules that are its own."""

    def test_no_two_roles_share_a_number(self):
        """No collision: data() returns the first branch matched, so a field returns another."""
        seen = {}
        for name in dir(gradient_library.GradientLibrary):
            if not name.endswith("Role"):
                continue
            number = getattr(gradient_library.GradientLibrary, name)
            if not isinstance(number, int):
                continue
            self.assertNotIn(
                number, seen,
                "%s and %s are both %d - data() returns whichever it "
                "tests first" % (name, seen.get(number), number))
            seen[number] = name

    def test_the_category_role_answers_a_LIST(self):
        """257 is matched with `for elem in data`, so a bare string would match per CHARACTER."""
        directory = tempfile.mkdtemp(prefix="amaze_grad_roles_")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        test_support.reset_database_singletons()
        _lay(os.path.join(directory, COLORS), {"categories": ["Warm"], "assets": [
            {"id": "aaa", "name": "Test", "categories": ["Warm"],
             "colors": [{"name": "red", "hex": "#ff0000"}]}]})
        lib = gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, directory))
        value = lib.data(lib.index(0, 0), lib.CategoryRole)
        self.assertIsInstance(
            value, list,
            "CategoryRole returned %r; the shared proxy iterates it, so "
            "a string matches per character" % (value,))


class EveryCallThePanelMakesOnTheColorsSidebarResolves(unittest.TestCase):
    """Read from source: every panel call on gradient_categories_model must exist."""

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
        """A call left to a deleted method raises a traceback when the user triggers it."""
        for attribute, model in (
                ("gradient_categories_model", gradient_library.GradientCategories),
                ("gradient_model", gradient_library.GradientLibrary)):
            with self.subTest(attribute):
                calls = self._calls_on(attribute)
                self.assertTrue(
                    calls,
                    "found no calls at all - the AST scan stopped matching, "
                    "which would make this check pass without testing anything")
                missing = {method: sites for method, sites in calls.items()
                           if not hasattr(model, method)}
                self.assertEqual(
                    {}, missing,
                    "the panel calls these on %s and it does not have "
                    "them: %s" % (model.__name__, missing))


class TheAllMarkerIsNotChurnedOnEverySave(unittest.TestCase):
    """The All row is the view, never a stored category: no edit writes it, and none is offered."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.dir = tempfile.mkdtemp(prefix="amaze_grad_all_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, COLORS)
        _lay(self.path, {"categories": ["Warm"],
                         "assets": [{"name": "ours", "id": "oursid", "colors": []}]})
        self.lib = gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))

    def test_an_ordinary_edit_writes_no_All_marker(self):
        self.lib.add_user_gradient("mine", "", {"values": [], "keys": []})
        library_db.flush()
        with open(self.path, encoding="utf-8") as fh:
            categories = json.load(fh).get("categories", {})
        self.assertEqual(["Warm"], sorted(categories),
                         "a Colors edit stored the All row as a category")

    def test_neither_marker_is_offered_as_a_category(self):
        """`_All`, or a plain All a hand edit or an older build left on disk."""
        document = _colors_document({"assets": []})
        document["categories"] = {"_All": {"order": 0}, "All": {"order": 1},
                                  "Warm": {"order": 2}}
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(document, fh, indent=1)
        test_support.reset_database_singletons()
        lib = gradient_library.GradientLibrary(
            preferences=_fixture_prefs(self, self.dir))
        self.assertEqual(["Warm"], lib.user_categories(),
                         "the save dialog offers All as a category to file under")


class TheGradientEntryIsResolvedOnce(unittest.TestCase):
    """Every GradientSection method gets its entry through `_entry_at`, which has the check."""

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
        self.assertEqual([], found, "a GradientSection method resolves its own entry, not via _entry_at")

    def test_an_index_the_proxy_has_dropped_answers_no_entry(self):
        """`_entry_at` checks for every method: an unmappable index gives no entry, not row -1's."""
        section = sections.GradientSection.__new__(sections.GradientSection)
        self.assertIsNone(sections.GradientSection._entry_at(section, None))


class ARampHelperIsTotal(unittest.TestCase):
    """`hou.Ramp` raises `InvalidSize` on mismatch, is float when empty. ▸r/ramp-and-walk-edges"""

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
        """The truncation must not change an ordinary gradient."""
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
    """Paints inside `data()`: every palette `data_to_ramp` takes paints. ▸r/ramp-and-walk-edges"""

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
