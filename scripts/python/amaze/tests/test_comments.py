"""Comments: one test per requirement in docs/requirements/comments.md."""

import os
import shutil
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from amaze.core import (documents, guard, library, library_db, library_files,  # noqa: E402
                        notes, texstore, users)
from amaze.tests import faults, test_support  # noqa: E402

MATERIALS = library_files.MATERIALS
GOLD, GLASS = "139888336889814930", "139888337058723210"    # two fixture materials


def read(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def text(words: str) -> dict:
    return {"t": "text", "text": words}


def bare(items) -> list:
    """Comment items without their id and author: what was written."""
    return [{key: value for key, value in item.items() if key not in ("id", "author")}
            for item in items]


class CommentsTest(unittest.TestCase):
    """A fixture library, its material GOLD, and a picture to paste."""

    def setUp(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        self.prefs = test_support.fixture_prefs(self)
        self.key = notes.note_key("material", GOLD)
        folder = test_support.scratch_dir("amaze_cm_shot_")
        self.addCleanup(shutil.rmtree, folder, True)
        self.shot = test_support.put(folder, "shot.png", b"pasted")

    def page(self, key: str, *items) -> bool:
        return notes.set_note(self.prefs, key, list(items))

    def picture(self, key: str) -> dict:
        """A picture pasted into the comment of `key`, as its item."""
        return {"t": "image", "src": notes.copy_image_into_library(self.prefs, self.shot, key),
                "text": "[image]"}

    def file_of(self, key: str, item: dict) -> str:
        return notes.image_path(self.prefs.dir, key, item["src"])

    def on_disk(self, name: str = MATERIALS) -> dict:
        return guard.Guard(self.prefs.dir).read(name).document

    def trashed(self, path: str) -> str:
        held = guard.Guard(self.prefs.dir)
        return held.in_trash(held.inside(path))

    def test_cm01_saving_a_comment_changes_only_its_own_page(self):
        glass, code = notes.note_key("material", GLASS), notes.note_key("code", "C1")
        self.assertTrue(self.page(glass, text("glass")) and self.page(code, text("loop")))
        other = documents.Library(self.prefs.dir, "u-other").document(MATERIALS)
        other.put(notes.SECTION, "theirs", {"items": [text("another session's")]})
        other.edit("assets", GLASS, name="Glass two")
        self.assertTrue(other.save())
        snippets = self.on_disk(library_files.CODE)
        self.assertTrue(self.page(self.key, text("gold")))
        saved = self.on_disk()
        self.assertEqual({GOLD, GLASS, "theirs"}, set(saved[notes.SECTION]))
        self.assertEqual("Glass two", saved["assets"][GLASS]["name"])
        self.assertEqual(snippets, self.on_disk(library_files.CODE))

    def test_cm02_an_unsaved_delete_keeps_the_comment_and_a_saved_one_drops_it(self):
        shown = self.picture(self.key)
        self.assertTrue(self.page(self.key, text("gold"), shown))
        library_db.document(self.prefs, MATERIALS).put_mine("favorites", GOLD, True)
        library_db.flush(self.prefs)
        model = library.MaterialLibrary(preferences=self.prefs)
        library_db.guard_of(self.prefs).disk = faults.FaultDisk(full_from=1)
        self.assertEqual(0, model.remove_rows([model.find_asset_row_by_id(GOLD)]))
        library_db.guard_of(self.prefs).disk = guard.Disk()
        library_db.flush(self.prefs)
        kept, path = self.on_disk(), self.file_of(self.key, shown)
        self.assertEqual(([text("gold"), shown], True, True), (
            bare(kept[notes.SECTION][GOLD]["items"]), os.path.isfile(path),
            kept["favorites"][test_support.FIXTURE_USER][GOLD]))
        self.assertEqual(1, model.remove_rows([model.find_asset_row_by_id(GOLD)]))
        dropped = self.on_disk()
        self.assertNotIn(GOLD, dropped[notes.SECTION])
        self.assertNotIn(GOLD, dropped.get("favorites", {}).get(test_support.FIXTURE_USER, {}))
        self.assertTrue(self.trashed(path))

    def test_cm03_no_picture_a_comment_names_is_trashed(self):
        first, second = notes.note_key("file", "first"), notes.note_key("file", "second")
        shared = self.picture(first)
        self.assertTrue(self.page(first, text("one"), shared) and self.page(second, shared))
        self.assertTrue(self.page(first, text("one, without it")))
        self.assertTrue(os.path.isfile(self.file_of(second, shared)), "a comment still shows it")
        shown = self.picture(self.key)
        self.assertTrue(self.page(self.key, text("gold"), shown))
        self.assertTrue(self.page(self.key, text("gold")))
        self.assertTrue(self.page(self.key, text("gold"), shown), "put back by an undo")
        self.assertEqual(b"pasted", read(self.file_of(self.key, shown)))

    def test_cm04_an_edit_changes_only_what_was_edited(self):
        coming = {"t": "image", "src": texstore.OWN_PREFIX + "comments/" + "f" * 32 + ".png",
                  "text": "[image: still syncing]"}
        self.assertTrue(self.page(self.key, text("one"), coming, {"t": "todo", "label": "two"}))
        before = notes.note_for(self.prefs, self.key)["items"]
        self.assertTrue(self.page(self.key, text("one"), coming, {"t": "todo", "label": "two"},
                                  text("three")))
        after = notes.note_for(self.prefs, self.key)["items"]
        self.assertEqual(before, after[:3])

    def test_cm20_a_comment_reads_back_in_the_order_written(self):
        written = [text("first"), {"t": "todo", "label": "second", "done": True},
                   self.picture(self.key), text("fourth")]
        self.assertTrue(self.page(self.key, *written))
        test_support.reset_database_singletons()
        self.assertEqual(written, bare(notes.note_for(self.prefs, self.key)["items"]))

    def test_cm21_each_item_names_its_author_and_an_unchanged_one_keeps_it(self):
        first = test_support.FIXTURE_USER
        self.assertTrue(self.page(self.key, text("the first's"), {"t": "todo", "label": "to do"}))
        before = notes.note_for(self.prefs, self.key)["items"]
        second = self.prefs.library_user = users.create(self.prefs, "Second")
        self.assertTrue(self.page(self.key, text("the first's"),
                                  {"t": "todo", "label": "to do", "done": True}, text("mine")))
        after = notes.note_for(self.prefs, self.key)["items"]
        self.assertEqual([(item["id"], first) for item in before] + [(after[2]["id"], second)],
                         [(item["id"], item["author"]) for item in after])

    def test_cm22_a_comment_with_nothing_left_is_removed(self):
        self.assertTrue(self.page(self.key, text("gold")))
        self.assertTrue(self.page(self.key, text("  "), {"t": "todo", "label": ""}))
        self.assertFalse(notes.has_note(self.prefs, self.key))
        self.assertNotIn(GOLD, self.on_disk()[notes.SECTION])

    def test_cm23_a_pasted_picture_is_copied_under_a_name_of_its_own(self):
        stamp = os.stat(self.shot).st_mtime_ns
        one, two = self.picture(self.key), self.picture(self.key)
        self.assertNotEqual(one["src"], two["src"])
        self.assertEqual((b"pasted", b"pasted", b"pasted", stamp), (
            read(self.file_of(self.key, one)), read(self.file_of(self.key, two)),
            read(self.shot), os.stat(self.shot).st_mtime_ns))

    def test_cm29_a_page_of_any_shape_reads_and_names_nothing_outside(self):
        held = library_db.document(self.prefs, MATERIALS)
        for ident, page in (("a", {"items": "text"}), ("b", {"items": [1, None, text("kept")]}),
                            ("c", {"items": {"t": "text"}})):
            held.put(notes.SECTION, ident, page)
            found = notes.note_for(self.prefs, notes.note_key("material", ident))
            self.assertTrue(all(isinstance(item, dict) for item in found.get("items", [])))
        for src in ("../../outside.png", "/outside.png", "$AMAZEASSET/../../outside.png"):
            self.assertEqual("", notes.image_path(self.prefs.dir, self.key, src))

    def test_cm30_a_picture_taken_out_of_a_comment_goes_to_the_trash(self):
        kept, taken = self.picture(self.key), self.picture(self.key)
        self.assertTrue(self.page(self.key, text("gold"), kept, taken))
        path = self.file_of(self.key, taken)
        self.assertTrue(self.page(self.key, text("gold"), kept))
        self.assertEqual((False, True), (os.path.exists(path),
                                         os.path.isfile(self.file_of(self.key, kept))))
        self.assertTrue(self.trashed(path))


class TypingTest(unittest.TestCase):
    """The Comments page of a fixture panel, its comments pane open on the Materials grid."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.panel.setAttribute(QtCore.Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.panel.show()    # a page never shown gets no hide event
        self.panel.pane.choose_tab("material")
        self.panel.btn_notes.setChecked(True)
        self.page = self.panel.notes_panel

    def select(self, asset_id: str) -> None:
        """Select the tile of `asset_id`, as a click does."""
        pane = self.panel.pane
        model, flags = pane.material_model, QtCore.QItemSelectionModel.SelectionFlag
        index = pane.material_sorted_model.mapFromSource(
            model.index(model.find_asset_row_by_id(asset_id), 0))
        pane.material_selection_model.setCurrentIndex(index, flags.ClearAndSelect | flags.Rows)

    def type(self, words: str) -> None:
        self.page.text_edit.moveCursor(self.page.text_edit.textCursor().MoveOperation.End)
        self.page.text_edit.insertPlainText(" " + words)

    @staticmethod
    def saved(library: str, asset_id: str) -> str:
        """The text of the comment of `asset_id`, as it is on disk in `library`."""
        pages = guard.Guard(library).read(MATERIALS).document.get(notes.SECTION) or {}
        items = (pages.get(asset_id) or {}).get("items", [])
        return " ".join(" ".join(item.get("text", "") for item in items).split())

    def test_cm10_what_is_typed_is_saved_at_once_to_where_it_was_typed(self):
        first, pane, notes_open = self.panel.pane.prefs.dir, self.panel.pane, self.panel.btn_notes
        library_db.set_scheduler(pane.library._save_timer.start)    # saves wait, as in Houdini
        self.select(GOLD)
        self.type("one")
        self.assertTrue(test_support.pump_until(lambda: "one" in self.saved(first, GOLD), 1.0),
                        "what was typed was not saved within a second")
        self.type("two")
        self.select(GLASS)
        self.assertEqual("one two", self.saved(first, GOLD), "lost when the selection changed")
        self.type("three")
        pane.material_model.set_tile_name(
            pane.material_model.find_asset_row_by_id(GLASS), "Glass renamed")
        self.type("four")
        notes_open.setChecked(False)
        self.assertEqual("three four", self.saved(first, GLASS), "lost by a rename or a hide")
        notes_open.setChecked(True)
        self.type("five")
        self.page.close()
        self.assertEqual("three four five", self.saved(first, GLASS), "lost when closed")
        self.assertTrue(_app.aboutToQuit.disconnect(self.page.flush), "nothing saves at quit")
        self.page.show()
        self.type("six")
        self.page.flush()    # what quitting calls; no timer fires after it
        self.assertEqual("three four five six", self.saved(first, GLASS), "lost when Houdini quit")
        self.type("seven")
        other = test_support.seeded_library(self)
        self.assertTrue(test_support.apply_library(self, self.panel, other, user="Second"))
        self.assertEqual(("three four five six seven", ""), (
            self.saved(first, GLASS), self.saved(other, GLASS)), "lost when the library changed")
        self.select(GOLD)
        self.type("eight")
        self.panel.deleteLater()
        QtWidgets.QApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        self.assertEqual("eight", self.saved(other, GOLD), "lost when the panel was deleted")

if __name__ == "__main__":
    unittest.main()
