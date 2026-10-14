"""Two machines editing one library: a field a peer changed must survive, and a real conflict must be told to the user rather than silently won."""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from PySide6 import QtWidgets

from amaze.core import database
from amaze.tests import test_support

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

    def test_a_peer_edit_to_renderer_is_not_destroyed(self):
        self._write(self._document())
        db = self._loaded()
        self._peer_writes(renderer="Redshift")

        db.set({"assets": [dict(db._data["assets"][0], name="renamed here")],
                "categories": ["_All"], "tags": []})
        self.assertTrue(db.save())

        self.assertEqual("Redshift", self._row().get("renderer"),
                         "the other machine's renderer was overwritten")

    def test_a_field_we_never_touched_takes_the_peer_value(self):
        """Neither side is editing `date`; theirs is simply newer."""
        self._write(self._document())
        db = self._loaded()
        self._peer_writes(date="2026-08-31 12:00:00")

        db.set({"assets": [dict(db._data["assets"][0], name="renamed here")],
                "categories": ["_All"], "tags": []})
        self.assertTrue(db.save())

        self.assertEqual("2026-08-31 12:00:00", self._row().get("date"))


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

    def test_a_field_the_other_machine_dropped_does_not_come_back(self):
        self._write(self._document(description="theirs to remove"))
        db = self._loaded()

        theirs = self._on_disk()
        theirs["assets"][0].pop("description")
        self._write(theirs)

        db.set({"assets": [dict(db._data["assets"][0], name="renamed here")],
                "categories": ["_All"], "tags": []})
        self.assertTrue(db.save())

        self.assertNotIn(
            "description", self._row(),
            "they removed the field and our save wrote it straight back")

    def test_a_field_we_changed_survives_their_removal(self):
        self._write(self._document(description="as loaded"))
        db = self._loaded()
        theirs = self._on_disk()
        theirs["assets"][0].pop("description")
        self._write(theirs)

        row = dict(db._data["assets"][0], description="ours now")
        db.set({"assets": [row], "categories": ["_All"], "tags": []})
        self.assertTrue(db.save())

        self.assertEqual("ours now", self._row().get("description"),
                         "our edit lost to their removal")


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

    def test_their_recolour_is_adopted(self):
        self._write(self._coloured({"Wood": "#111111"}))
        db = self._loaded()
        self._their_colours({"Wood": "#222222"})

        self._our_unrelated_save(db)

        self.assertEqual("#222222", self._colours_on_disk().get("Wood"),
                         "our save wrote the old colour back over theirs")
        self.assertEqual("#222222", db._data["category_colors"].get("Wood"),
                         "their colour reached disk but not this session")

    def test_their_uncolour_is_adopted(self):
        self._write(self._coloured({"Wood": "#111111", "Metal": "#333333"}))
        db = self._loaded()
        self._their_colours({"Metal": "#333333"})

        self._our_unrelated_save(db)

        self.assertNotIn("Wood", self._colours_on_disk(),
                         "they cleared the colour and our save put it back")
        self.assertEqual("#333333", self._colours_on_disk().get("Metal"))

    def test_our_recolour_survives_their_unrelated_save(self):
        self._write(self._coloured({"Wood": "#111111"}))
        db = self._loaded()
        db.set({"category_colors": {"Wood": "#444444"}})
        self._peer_writes(name="renamed by them")

        self.assertTrue(db.save())

        self.assertEqual("#444444", self._colours_on_disk().get("Wood"),
                         "our own recolour lost to a save that never "
                         "touched the colour")

    def test_our_uncolour_survives_their_unrelated_save(self):
        self._write(self._coloured({"Wood": "#111111"}))
        db = self._loaded()
        db.set({"category_colors": {}})
        self._peer_writes(name="renamed by them")

        self.assertTrue(db.save())

        self.assertNotIn("Wood", self._colours_on_disk(),
                         "a colour we cleared came back from their copy")


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


class AnAdoptedFieldReachesTheCaller(_Case):
    """H6: adopted values were kept as whole rows nobody read field-wise."""

    def test_the_connector_names_the_field_it_adopted(self):
        self._write(self._document())
        db = self._loaded()
        self._peer_writes(code="int i = 42;")

        db.set({"assets": [dict(db._data["assets"][0], name="renamed here")],
                "categories": ["_All"], "tags": []})
        self.assertTrue(db.save())

        adopted = db.take_adopted_fields()
        self.assertIn(("ASSET0", "code", "int i = 42;"), adopted,
                      "nothing told the model which field changed, so the "
                      "next ordinary save writes the old value back")


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

    def test_a_peer_deletion_stays_deleted(self):
        self.assertTrue(self.model.save(), "premise: the first save failed")
        document = self._disk()
        victim = str(document["assets"][2]["id"])
        document["assets"] = [row for row in document["assets"]
                              if str(row.get("id")) != victim]
        self._write(document)

        self._sidebar_save_then_asset_save()

        self.assertNotIn(
            victim, [str(row.get("id")) for row in self._disk()["assets"]],
            "the peer's deletion was written back: the sidebar save merged "
            "it, and the asset save rebuilt the list from a model that "
            "still held the row")
        self.assertNotIn(victim, [str(a.mat_id) for a in self.model.assets])

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
            real_write(path, data, **kw)
            self._write(before)    # the winner's rename lands on top of ours
            hostos.write_json_atomic = real_write    # once only
            return None

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
