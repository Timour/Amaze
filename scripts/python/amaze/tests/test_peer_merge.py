"""Two machines editing one library: a field a peer changed must survive, and a real conflict must be told to the user rather than silently won."""

import json
import os
import shutil
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
