"""Two machines editing one library: a field a peer changed must survive, and a real conflict must be told to the user rather than silently won."""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from PySide6 import QtCore, QtWidgets

from amaze.core import category, database
from amaze.tests import test_support

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])    # ▸p/first-app-picks-the-platform


class _Case(unittest.TestCase):

    FILENAME = "code.json"

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_peer_merge_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, self.FILENAME)
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)

    def _document(self, **fields):
        row = {"id": "ASSET0", "name": "snippet", "code": "int i = 0;",
               "renderer": "Karma", "date": "2026-01-01 00:00:00"}
        row.update(fields)
        return {"version": database.SCHEMA_VERSION,
                "categories": ["_All"], "tags": [], "assets": [row]}

    def _write(self, data):
        with open(self.path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, indent=4)

    def _loaded(self):
        """A connector holding the file, the way a session does."""
        db = database.DatabaseConnector(self.FILENAME)
        db.load(self.dir + os.sep)
        return db

    def _on_disk(self):
        with open(self.path, encoding="utf-8-sig") as handle:
            return json.load(handle)

    def _row(self):
        return self._on_disk()["assets"][0]

    def _peer_writes(self, **fields):
        """The other machine's save, landing behind this session's back."""
        theirs = self._on_disk()
        theirs["assets"][0].update(fields)
        self._write(theirs)


class APeerFieldEditSurvivesOurSave(_Case):
    """The merge knew eight field names; everything else was overwritten."""

    def test_a_peer_edit_to_code_is_not_destroyed(self):
        self._write(self._document())
        db = self._loaded()
        self._peer_writes(code="int i = 42;")

        db.set({"assets": [dict(db._data["assets"][0], name="renamed here")],
                "categories": ["_All"], "tags": []})
        self.assertTrue(db.save())

        row = self._row()
        self.assertEqual("int i = 42;", row.get("code"),
                         "the other machine's snippet text was overwritten")
        self.assertEqual("renamed here", row.get("name"),
                         "our own rename did not land")
        self.assertIn(("ASSET0", "code", "int i = 42;"),
                      db.take_adopted_fields(),
                      "nothing told the model which field changed, so the "
                      "next ordinary save writes the old value back")


class TheAuditsNamedScenarios(_Case):
    """The reproductions the two-panel audit ran, as permanent tests."""

    def test_2c_both_machines_rename_a_different_row(self):
        """Neither rename may be lost: they touch different rows."""
        document = self._document()
        document["assets"].append({"id": "ASSET1", "name": "second",
                                   "code": "", "renderer": "Karma",
                                   "date": "2026-01-01 00:00:00"})
        self._write(document)
        db = self._loaded()

        self._peer_writes()    # no change: take a clean peer copy first
        theirs = self._on_disk()
        theirs["assets"][1]["name"] = "renamed by them"
        self._write(theirs)

        rows = [dict(db._data["assets"][0], name="renamed by us"),
                dict(db._data["assets"][1])]
        db.set({"assets": rows, "categories": ["_All"], "tags": []})
        self.assertTrue(db.save())

        names = {row["id"]: row.get("name") for row in self._on_disk()["assets"]}
        self.assertEqual("renamed by us", names["ASSET0"])
        self.assertEqual("renamed by them", names["ASSET1"],
                         "the other machine's rename was lost")

    def test_2d_a_category_the_other_machine_removed_stays_removed(self):
        """Categories union, so a removal used to come straight back."""
        document = self._document()
        document["categories"] = ["_All", "Wood", "Metal"]
        self._write(document)
        db = self._loaded()

        theirs = self._on_disk()
        theirs["categories"] = ["_All", "Wood"]
        theirs["assets"][0]["name"] = "nudged"    # so the file is seen to move
        self._write(theirs)

        db.set({"assets": [dict(db._data["assets"][0])],
                "categories": list(db._data["categories"]), "tags": []})
        self.assertTrue(db.save())

        self.assertNotIn(
            "Metal", self._on_disk()["categories"],
            "a category the other machine removed was put back by our save")

    def test_2d_a_category_this_machine_removed_stays_removed(self):
        """A rename is a removal too: the old name must not come back with an unrelated merge."""
        document = self._document()
        document["categories"] = ["_All", "Wood", "Metal"]
        self._write(document)
        db = self._loaded()
        self._peer_writes(name="nudged elsewhere")    # so the save merges

        db.set({"assets": [dict(db._data["assets"][0])],
                "categories": ["_All", "Wood", "Steel"], "tags": []})
        self.assertTrue(db.save())

        self.assertEqual(
            ["_All", "Wood", "Steel"], self._on_disk()["categories"],
            "a category renamed here was put back by a merge that never "
            "touched it")

    def test_2d_a_category_each_machine_added_survives(self):
        self._write(self._document())
        db = self._loaded()

        theirs = self._on_disk()
        theirs["categories"] = ["_All", "FromThem"]
        self._write(theirs)

        db.set({"assets": [dict(db._data["assets"][0])],
                "categories": ["_All", "FromUs"], "tags": []})
        self.assertTrue(db.save())

        after = self._on_disk()["categories"]
        self.assertIn("FromUs", after)
        self.assertIn("FromThem", after, "their new category was dropped")


class APeerFieldRemovalIsHonoured(_Case):
    """The same rule the category list follows: gone from disk, in our base, untouched by us, is THEIR removal."""

    def test_their_removal_stands_unless_we_changed_the_field(self):
        absent = object()
        for why, ours, expected in (
                ("they removed it and our save wrote it back",
                 {"name": "renamed here"}, absent),
                ("our edit lost to their removal",
                 {"description": "ours now"}, "ours now")):
            with self.subTest(why):
                test_support.reset_database_singletons()
                self._write(self._document(description="as loaded"))
                db = self._loaded()
                theirs = self._on_disk()
                theirs["assets"][0].pop("description")
                self._write(theirs)
                db.set({"assets": [dict(db._data["assets"][0], **ours)],
                        "categories": ["_All"], "tags": []})
                self.assertTrue(db.save())
                self.assertEqual(expected,
                                 self._row().get("description", absent), why)


class ACategoryColourIsJudgedAgainstWhatWeLoaded(_Case):
    """Colours merge per category name against the table as we last read it - ours won every name."""

    def _coloured(self, colours):
        document = self._document()
        document["categories"] = ["_All", "Wood", "Metal"]
        document["category_colors"] = dict(colours)
        return document

    def _their_colours(self, colours):
        theirs = self._on_disk()
        theirs["category_colors"] = dict(colours)
        self._write(theirs)

    def _colours_on_disk(self):
        return self._on_disk().get("category_colors", {})

    def _our_unrelated_save(self, db):
        db.set({"assets": [dict(db._data["assets"][0], name="renamed here")]})
        self.assertTrue(db.save())

    def test_a_colour_follows_whichever_side_moved_it(self):
        """Theirs is adopted where we left a name alone; ours stands where they did."""
        absent = object()
        for why, base, ours, theirs, expected in (
                ("their recolour", {"Wood": "#111111"}, None,
                 {"Wood": "#222222"}, {"Wood": "#222222"}),
                ("their uncolour", {"Wood": "#111111", "Metal": "#333333"},
                 None, {"Metal": "#333333"}, {"Wood": absent, "Metal": "#333333"}),
                ("our recolour", {"Wood": "#111111"}, {"Wood": "#444444"},
                 None, {"Wood": "#444444"}),
                ("our uncolour", {"Wood": "#111111"}, {}, None,
                 {"Wood": absent})):
            with self.subTest(why):
                test_support.reset_database_singletons()
                self._write(self._coloured(base))
                db = self._loaded()
                if ours is not None:
                    db.set({"category_colors": ours})
                if theirs is None:
                    self._peer_writes(name="renamed by them")
                else:
                    self._their_colours(theirs)
                if ours is None:
                    self._our_unrelated_save(db)
                else:
                    self.assertTrue(db.save())
                for name, colour in expected.items():
                    self.assertEqual(colour,
                                     self._colours_on_disk().get(name, absent),
                                     "%s: %s is wrong on disk" % (why, name))
                    self.assertEqual(colour,
                                     db._data["category_colors"].get(name, absent),
                                     "%s: %s is wrong in this session" % (why, name))

    def test_both_recolouring_one_name_keeps_ours_and_says_so(self):
        self._write(self._coloured({"Wood": "#111111"}))
        db = self._loaded()
        db.set({"category_colors": {"Wood": "#444444"}})
        self._their_colours({"Wood": "#222222"})

        alerts = []
        with mock.patch.object(database.debug, "alert",
                               lambda message, **kw: alerts.append(message)):
            self.assertTrue(db.save())

        self.assertEqual(
            ("#444444", 1), (self._colours_on_disk().get("Wood"), len(alerts)),
            "both machines recoloured Wood: ours must stand AND the user "
            "must be told the other colour was discarded")


class ARealConflictIsTOLD(_Case):
    """Local wins a true conflict - but never in silence."""

    def test_both_editing_one_field_alerts_the_user(self):
        self._write(self._document())
        db = self._loaded()
        self._peer_writes(name="their name")

        alerts = []
        real = database.debug.alert
        database.debug.alert = lambda message, **kw: alerts.append(str(message))
        self.addCleanup(setattr, database.debug, "alert", real)

        db.set({"assets": [dict(db._data["assets"][0], name="our name")],
                "categories": ["_All"], "tags": []})
        self.assertTrue(db.save())

        self.assertEqual("our name", self._row().get("name"),
                         "local must win a true conflict")
        self.assertTrue(
            alerts,
            "the other machine's edit was discarded and only a debug line "
            "said so - the user was never told")


class AnAdoptedFieldReachesTheModel(unittest.TestCase):
    """H6's other half: the connector names the field, the MODEL must apply it."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.model = self.panel.material_model
        self.path = os.path.join(self.panel.prefs.dir, "library.json")

    def _disk(self):
        with open(self.path, encoding="utf-8-sig") as handle:
            return json.load(handle)

    def _write(self, document):
        with open(self.path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, indent=4)

    def test_a_peer_field_edit_is_in_the_model_after_our_save(self):
        self.assertTrue(self.model.save(), "premise: the first save failed")
        target = next(a for a in self.model.assets if a.name)

        document = self._disk()
        row = next(r for r in document["assets"]
                   if str(r.get("id")) == str(target.mat_id))
        row["about"] = "written by the other machine"
        self._write(document)

        self.assertTrue(self.model.save())

        self.assertEqual(
            "written by the other machine", target.about,
            "the connector adopted the field but the model kept its old "
            "value, so the next ordinary save writes it back out")


class ASidebarSaveDoesNotStrandWhatItMerged(unittest.TestCase):
    """The sidebar shares the asset model's connector, so what ITS save merges must reach the model."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.model = self.panel.material_model
        self.path = os.path.join(self.panel.prefs.dir, "library.json")

    def _disk(self):
        with open(self.path, encoding="utf-8-sig") as handle:
            return json.load(handle)

    def _write(self, document):
        with open(self.path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, indent=4)

    def _sidebar_save_then_asset_save(self):
        self.assertTrue(self.panel.category_model.save(),
                        "premise: the sidebar save was refused")
        self.assertTrue(self.model.save(),
                        "premise: the asset save was refused")

    def test_a_peer_deletion_leaves_the_grid_and_stays_deleted(self):
        self.assertTrue(self.model.save(), "premise: the first save failed")
        document = self._disk()
        victim = str(document["assets"][2]["id"])
        document["assets"] = [row for row in document["assets"]
                              if str(row.get("id")) != victim]
        self._write(document)

        self.assertTrue(self.panel.category_model.save(),
                        "premise: the sidebar save was refused")
        self.assertNotIn(
            victim, [str(a.mat_id) for a in self.model.assets],
            "the sidebar's save took in the deletion, but the grid keeps "
            "the row until the next asset save or refresh")
        self.assertTrue(self.model.save(),
                        "premise: the asset save was refused")
        self.assertNotIn(
            victim, [str(row.get("id")) for row in self._disk()["assets"]],
            "the peer's deletion was written back: the sidebar save merged "
            "it, and the asset save rebuilt the list from a model that "
            "still held the row")

    def test_a_peer_rename_is_not_written_back(self):
        self.assertTrue(self.model.save(), "premise: the first save failed")
        target = next(a for a in self.model.assets if a.name)
        document = self._disk()
        row = next(r for r in document["assets"]
                   if str(r.get("id")) == str(target.mat_id))
        row["name"] = "renamed by the other machine"
        self._write(document)

        self._sidebar_save_then_asset_save()

        on_disk = next(r for r in self._disk()["assets"]
                       if str(r.get("id")) == str(target.mat_id))
        self.assertEqual(
            "renamed by the other machine", on_disk.get("name"),
            "the sidebar save adopted the peer's rename, and the asset "
            "save wrote the model's stale name straight back over it")


class TheSidebarHearsWhatASaveMerged(unittest.TestCase):
    """A save merging another machine's categories tells the sidebar's views at once."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.sidebar = self.panel.category_model
        self.path = os.path.join(self.panel.prefs.dir, "library.json")
        self.assertTrue(self.panel.material_model.save(),
                        "premise: the first save failed")

    def _disk(self):
        with open(self.path, encoding="utf-8-sig") as handle:
            return json.load(handle)

    def _write(self, document):
        with open(self.path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, indent=4)

    def _view(self):
        """A proxy maps only what the model has signalled, as every view does."""
        proxy = QtCore.QSortFilterProxyModel()
        proxy.setSourceModel(self.sidebar)
        proxy.rowCount()
        self.addCleanup(proxy.setSourceModel, None)
        return proxy

    def _merged_by(self, save, change):
        view = self._view()
        document = self._disk()
        change(document["categories"])
        self._write(document)
        save()
        self.assertEqual(
            (document["categories"], len(document["categories"])),
            (list(self.sidebar._categories), view.rowCount()),
            "the save merged the categories, but the sidebar's views were "
            "never told, so they still count the old rows")

    def test_a_category_merged_by_either_save_reaches_the_views(self):
        for why, save, change in (
                ("added, by a sidebar save", self.sidebar.save,
                 lambda cats: cats.append("From Elsewhere")),
                ("added, by an asset save", self.panel.material_model.save,
                 lambda cats: cats.append("Also Elsewhere")),
                ("removed, by an asset save", self.panel.material_model.save,
                 lambda cats: cats.remove("usds"))):
            with self.subTest(why):
                self._merged_by(save, change)


class AColourTakenInIsPainted(unittest.TestCase):
    """A colour set on another machine reaches the sidebar and the grid the moment a save takes it in."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.path = os.path.join(self.panel.prefs.dir, "library.json")
        self.assertTrue(self.panel.material_model.save(),
                        "premise: the first save failed")

    def _told(self, model, role):
        """Whether the views heard of `role` - a dataChanged naming it, or a reset."""
        heard = []
        model.dataChanged.connect(
            lambda first, last, roles=None: heard.append(
                not roles or role in roles))
        model.modelReset.connect(lambda: heard.append(True))
        return heard

    def test_a_colour_set_elsewhere_is_painted_at_once(self):
        sidebar, grid = self.panel.category_model, self.panel.material_model
        told_sidebar = self._told(sidebar, category.SIDEBAR_COLOR_ROLE)
        told_grid = self._told(grid, grid.CategoryColorRole)
        with open(self.path, encoding="utf-8-sig") as handle:
            document = json.load(handle)
        document["category_colors"] = {"Karma_Mats": "#123456"}
        with open(self.path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, indent=4)

        self.assertTrue(sidebar.save(), "premise: the sidebar save failed")

        row = next(index for index, asset in enumerate(grid.assets)
                   if list(asset.categories)[:1] == ["Karma_Mats"])
        self.assertEqual(
            ("#123456", "#123456", True, True),
            (sidebar.color_of("Karma_Mats"), grid.category_color(row),
             any(told_sidebar), any(told_grid)),
            "the colour was taken in, but the sidebar and the grid were not "
            "told, so it shows only on the next repaint")


class TheBaselineIsWhatIsOnDisk(_Case):
    """3a: the loser of a same-tick save recorded the bytes it serialised."""

    def test_a_clobbered_save_does_not_read_as_a_peer_deleting_our_row(self):
        """Our write lands, another machine's rename overwrites it in the same instant, and our next save must not read our own missing row as their deletion. ▸p/merge-needs-a-base"""
        from amaze.helpers import hostos

        self._write(self._document())
        db = self._loaded()
        before = self._on_disk()

        real_write = hostos.write_json_atomic

        def clobbered(path, data, **kw):
            answer = real_write(path, data, **kw)
            self._write(before)    # the winner's rename lands on top of ours
            hostos.write_json_atomic = real_write    # once only
            return answer

        hostos.write_json_atomic = clobbered
        self.addCleanup(setattr, hostos, "write_json_atomic", real_write)

        ours = dict(db._data["assets"][0])
        db.set({"assets": [ours, {"id": "ASSET1", "name": "ours alone"}],
                "categories": ["_All"], "tags": []})
        self.assertTrue(db.save())
        self.assertTrue(db.save(), "the second save was refused")

        ids = [row.get("id") for row in self._on_disk()["assets"]]
        self.assertIn(
            "ASSET1", ids,
            "our row was lost: the save recorded the bytes it serialised, so "
            "the next one read our own clobbered row as a peer's deletion")

    def test_the_baseline_after_a_save_matches_the_file(self):
        self._write(self._document())
        db = self._loaded()
        db.set({"assets": [dict(db._data["assets"][0], name="ours")],
                "categories": ["_All"], "tags": []})
        self.assertTrue(db.save())

        from amaze.helpers import hostos
        self.assertEqual(hostos.fingerprint_of(self.path), db._disk_stat,
                         "the connector remembered the bytes it serialised, "
                         "not the file - so its next save reads its own row "
                         "as a peer's deletion")


class TheBaselineIsTheBytesParsed(_Case):
    """A write landing between the parse and the fingerprint must be merged, never overwritten."""

    def _lands_after_the_parse(self, document):
        """Writes `document` the moment the next read of the database is parsed."""
        real_loads = json.loads
        armed = [True]

        def sneaky(*args, **kwargs):
            parsed = real_loads(*args, **kwargs)
            if armed[0] and isinstance(parsed, dict) and "assets" in parsed:
                armed[0] = False
                self._write(document)
            return parsed

        return mock.patch.object(json, "loads", sneaky)

    def _rename_here(self, db):
        db.set({"assets": [dict(db._data["assets"][0], name="renamed here")],
                "categories": ["_All"], "tags": []})
        self.assertTrue(db.save())

    def test_a_write_during_the_load_is_merged(self):
        self._write(self._document())
        with self._lands_after_the_parse(self._document(code="int i = 42;")):
            db = self._loaded()
        self._rename_here(db)
        self.assertEqual(
            {"code": "int i = 42;", "name": "renamed here"},
            {"code": self._row().get("code"), "name": self._row().get("name")},
            "the write that landed during the load was overwritten")

    def test_a_write_during_a_refresh_is_merged(self):
        self._write(self._document())
        db = self._loaded()
        self._peer_writes(date="2026-09-01 00:00:00")
        later = self._on_disk()
        later["assets"][0]["code"] = "int i = 7;"
        with self._lands_after_the_parse(later):
            self.assertTrue(db.refresh(), "premise: the refresh saw nothing")
        self._rename_here(db)
        self.assertEqual(
            {"code": "int i = 7;", "date": "2026-09-01 00:00:00"},
            {"code": self._row().get("code"), "date": self._row().get("date")},
            "the write that landed during the refresh was overwritten")

    def test_a_migrated_row_is_judged_against_its_migrated_self(self):
        """A row minted its id at load; the base must hold it under that id."""
        row = {"name": "snippet", "code": "int i = 0;", "renderer": "Karma",
               "date": "2026-01-01 00:00:00"}
        self._write({"version": 7, "categories": ["_All"], "assets": [row]})
        minted = database._minted_id(dict(row), 0)
        db = self._loaded()
        self.assertEqual(minted, db._data["assets"][0].get("id"),
                         "premise: the load did not mint the expected id")
        self._write({"version": database.SCHEMA_VERSION,
                     "categories": ["_All"],
                     "assets": [dict(row, id=minted, name="renamed there")]})
        alerts = []
        with mock.patch.object(database.debug, "alert",
                               lambda message, **kw: alerts.append(message)):
            db.set({"assets": [dict(db._data["assets"][0],
                                    code="int i = 1;")]})
            self.assertTrue(db.save())
        self.assertEqual(
            {"name": "renamed there", "conflicts told": 0},
            {"name": self._row().get("name"), "conflicts told": len(alerts)},
            "a rename made elsewhere read as a conflict: the merge base "
            "was the file before its ids were minted")


if __name__ == "__main__":
    unittest.main()
