"""Comments: one test per requirement in docs/requirements/comments.md."""

import json
import os
import shutil
import types
import unittest
import zipfile
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from amaze.core import (category, documents, file_library, guard, library,  # noqa: E402
                        library_db, library_files, locations, model_registry, notes, packages,
                        texstore, users)
from amaze.helpers import hostos  # noqa: E402
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

    def test_cm24_a_picture_not_here_shows_its_fallback_then_itself_once_it_arrives(self):
        from amaze.pane import comment_document, comments
        coming = {"t": "image", "src": texstore.OWN_PREFIX + "comments/" + "f" * 32 + ".png",
                  "text": "[image: still syncing]"}
        self.assertTrue(self.page(self.key, text("gold"), coming))
        document = QtGui.QTextDocument()
        shown = comment_document.CommentDocument(document)

        def opened() -> tuple:
            """The comment as the Comments pane opens it: its last line and its pictures."""
            shown.load(self.prefs.dir, self.key, comments.items_of(self.prefs, self.key))
            return (document.toPlainText().split("\n")[-1],
                    sum(comment_document.is_image_block(document.findBlockByNumber(number))
                        for number in range(document.blockCount())))

        self.assertEqual(("[image: still syncing]", 0), opened())
        os.makedirs(os.path.dirname(self.file_of(self.key, coming)), exist_ok=True)
        self.assertTrue(QtGui.QImage(4, 4, QtGui.QImage.Format.Format_RGB32).save(
            self.file_of(self.key, coming)))
        self.assertEqual((1, False), (opened()[1], "still syncing" in document.toPlainText()))

    def test_cm25_a_files_comment_follows_its_location_through_every_change(self):
        root = test_support.scratch_dir("amaze_cm_files_")
        self.addCleanup(shutil.rmtree, root, True)
        a, b = os.path.join(root, "a"), os.path.join(root, "b")
        shot = test_support.put(root, "a/sub/shot.exr", b"exr")
        written = [text("check the gamma")]

        def comment(path: str) -> list:
            key = notes.note_key("file", locations.file_ident(self.prefs, path))
            return bare(notes.note_for(self.prefs, key).get("items", []))

        self.assertTrue(locations.register(self.prefs, a))
        self.assertTrue(notes.set_note(self.prefs, notes.note_key(
            "file", locations.file_ident(self.prefs, shot)), written))
        self.assertTrue(locations.set_field(self.prefs, a, "name", "Shots"))
        self.assertEqual(written, comment(shot), "lost by a rename")
        os.rename(a, b)
        shot = os.path.join(b, "sub", "shot.exr")
        self.assertTrue(locations.relocate_record(self.prefs, a, b))
        self.assertEqual(written, comment(shot), "lost by a relocate")
        for where, added in (("inside", os.path.join(b, "sub")), ("above", root)):
            self.assertTrue(locations.register(self.prefs, added))
            self.assertEqual(written, comment(shot), "lost by a location added " + where)
        inner = hostos.storage_path_key(os.path.join(b, "sub"))
        other = documents.Library(self.prefs.dir, "u-other").document(library_files.FILES)
        other.put(locations.PATHS, "0" * 32, {"path": inner})    # another session's id for it
        other.put(notes.SECTION, locations.LOC_PREFIX + "0" * 32 + "/shot.exr",
                  {"items": [text("theirs")]})
        self.assertTrue(other.save())
        model_registry.refresh_all(self.prefs)
        self.assertEqual([text("theirs")] + written, comment(shot), "the two pages not joined")

    def test_cm26_removing_a_location_drops_its_comments_but_moves_those_still_covered(self):
        root = test_support.scratch_dir("amaze_cm_files_")
        self.addCleanup(shutil.rmtree, root, True)
        top, deep = (test_support.put(root, name, b"png") for name in ("a/top.png", "a/sub/deep.png"))
        a, sub = (hostos.canonical_path_key(os.path.join(root, *parts)) for parts in (("a",), ("a", "sub")))
        folders = file_library.FileFolders(self.prefs)
        for path in (a, sub):
            self.assertTrue(folders.add_folder(path))

        def key(path: str) -> str:
            return notes.note_key("file", locations.file_ident(self.prefs, path))

        pages = {locations.file_ident(self.prefs, path): [text(words)]
                 for path, words in ((top, "top"), (deep, "deep"))}
        self.assertTrue(notes.set_notes(self.prefs, {notes.note_key("file", ident): items
                                                     for ident, items in pages.items()}))
        held, moving = library_db.guard_of(self.prefs), locations.rekey_to_covering_location

        def full_at_the_move(*args):
            held.disk = faults.FaultDisk(full_from=1)
            try:
                return moving(*args)
            finally:
                held.disk = guard.Disk()

        with mock.patch.object(locations, "rekey_to_covering_location", full_at_the_move), \
                test_support.captured_log():
            folders.remove_folder(folders.row_of(sub))
        self.assertEqual(pages, {page: [text(item["text"]) for item in found["items"]] for page, found
                                 in self.on_disk(library_files.FILES)[notes.SECTION].items()},
                         "a failed move dropped a comment")
        self.assertTrue(folders.add_folder(sub))
        self.assertTrue(folders.remove_folder(folders.row_of(sub)))
        self.assertEqual(["deep"], [item["text"] for item in notes.note_for(
            self.prefs, key(deep)).get("items", [])], "a comment still covered was not moved")
        self.assertTrue(folders.remove_folder(folders.row_of(a)))
        self.assertEqual({}, self.on_disk(library_files.FILES).get(notes.SECTION) or {})

    def test_cm27_an_exported_asset_takes_its_comment_and_pictures_and_shows_them_imported(self):
        written = [text("gold"), self.picture(self.key)]
        self.assertTrue(self.page(self.key, *written))
        model = library.MaterialLibrary(self.prefs)
        out = os.path.join(test_support.scratch_dir("amaze_cm_package_"), "gold.amazepkg")
        self.addCleanup(shutil.rmtree, os.path.dirname(out), True)
        self.assertEqual(1, packages.write_package(out, [packages.collect_asset(model, GOLD)]))
        before = test_support.asset_ids(model)
        summary = packages.import_package({"material": model}, {"material": category.Categories(
            self.prefs)}, self.prefs, out)
        self.assertEqual(1, summary["imported"], summary)
        arrived, = test_support.arrived(model, before)
        key = notes.note_key("material", arrived.mat_id)
        items = notes.note_for(self.prefs, key)["items"]
        self.assertEqual(bare(written), bare(items))
        self.assertTrue(os.path.isfile(self.file_of(key, items[1])), "its picture did not travel")
        self.assertEqual(b"pasted", read(self.file_of(key, items[1])))

    def test_cm28_a_comment_that_comes_with_new_assets_is_written_only_for_saved_ones(self):
        from amaze.core import gradient_library, matx_import, matx_sources
        model, ours = library.MaterialLibrary(self.prefs), {}

        def pages(folder: str, name: str = MATERIALS) -> dict:
            found = guard.Guard(folder).read(name).document.get(notes.SECTION) or {}
            return {key: [item["text"] for item in page["items"]] for key, page in found.items()
                    if key not in ours}

        ours.update(pages(self.prefs.dir))
        good, refused = ({"type": "asset", "section": "material", "id": "%032x" % n,
                          "record": {"name": name}, "note": {"items": [text(name)]},
                          "files": {}, "textures": textures}
                         for n, name, textures in ((1, "saved", {}), (2, "refused", {"x": "x"})))
        out = os.path.join(test_support.scratch_dir("amaze_cm_package_"), "two.amazepkg")
        self.addCleanup(shutil.rmtree, os.path.dirname(out), True)
        with zipfile.ZipFile(out, "w") as bundle:
            bundle.writestr(packages.MANIFEST, json.dumps({"format": packages.FORMAT,
                                                           "entries": [good, refused]}))
            bundle.writestr("x", b"x")
        known = test_support.asset_ids(model)
        packages.import_package({"material": model}, {"material": category.Categories(
            self.prefs)}, self.prefs, out)
        saved, = test_support.arrived(model, known)
        self.assertEqual({str(saved.mat_id): ["saved"]}, pages(self.prefs.dir), "an import")

        def refused_save(builder, *args, **how):
            builder.setUserData("assetlib_id", "%032x" % 3)    # stamped, but no row was saved
            ours[None] = builder

        record = matx_sources.MatxRecord(source="Test", uid="brick", title="Brick",
                                         kind="values", payload={})
        source = types.SimpleNamespace(page_url=lambda record: "https://example.invalid/brick",
                                       fetch=lambda *a, **k: {"values": {"color": [0.5, 0.4, 0.3]}})
        ok, why = matx_import.import_record(record, source, None, model, self.prefs,
                                             save=refused_save)
        self.assertEqual((False, True, {str(saved.mat_id): ["saved"]}), (
            ok, None in ours, pages(self.prefs.dir)), why)
        colours = gradient_library.GradientLibrary(self.prefs)
        switched = test_support.with_fixture_user(test_support.fresh_library(self))
        self.prefs.dir = switched    # the folder changed, the rows not switched yet
        self.assertEqual(0, colours.seed_curated_palettes(gradient_library.GradientCategories(
            self.prefs)))
        self.assertEqual({}, pages(switched, library_files.COLORS), "a starter set")

    def test_cm29_a_page_of_any_shape_reads_and_names_nothing_outside(self):
        held = library_db.document(self.prefs, MATERIALS)
        for ident, page in (("a", {"items": "text"}), ("b", {"items": [1, None, text("kept")]}),
                            ("c", {"items": {"t": "text"}})):
            held.put(notes.SECTION, ident, page)
            found = notes.note_for(self.prefs, notes.note_key("material", ident))
            self.assertTrue(all(isinstance(item, dict) for item in found.get("items", [])))
        outside = ["../../outside.png", "/outside.png", "$AMAZEASSET/../../outside.png"]
        if os.name == "nt":    # another drive in the path: joined, it leaves the folder it is joined to
            other = "Y:" if self.prefs.dir.upper().startswith("Z") else "Z:"
            outside[:0] = ["$AMAZEASSET/%s/outside.png" % other, other + "outside.png"]
        for src in outside:
            self.assertEqual("", notes.image_path(self.prefs.dir, self.key, src), src)

    def test_cm30_a_picture_taken_out_of_a_comment_goes_to_the_trash(self):
        kept, taken = self.picture(self.key), self.picture(self.key)
        self.assertTrue(self.page(self.key, text("gold"), kept, taken))
        path = self.file_of(self.key, taken)
        self.assertTrue(self.page(self.key, text("gold"), kept))
        self.assertEqual((False, True), (os.path.exists(path),
                                         os.path.isfile(self.file_of(self.key, kept))))
        self.assertTrue(self.trashed(path))


class TypingTest(unittest.TestCase):
    """The Amaze pane on the fixture library, its Comments pane open on the Materials grid."""

    def setUp(self):
        self.panel = test_support.fixture_qml_pane(self)
        self.panel.pane.choose_tab("material")
        self.panel.state.showComments(True)
        QtWidgets.QApplication.processEvents()

    def select(self, asset_id: str) -> None:
        """Select the tile of `asset_id`, as a click does."""
        pane = self.panel.pane
        model, flags = pane.material_model, QtCore.QItemSelectionModel.SelectionFlag
        index = pane.material_sorted_model.mapFromSource(
            model.index(model.find_asset_row_by_id(asset_id), 0))
        pane.material_selection_model.setCurrentIndex(index, flags.ClearAndSelect | flags.Rows)

    def type(self, words: str) -> None:
        cursor = QtGui.QTextCursor(self.panel.pane.comments.document.document)
        cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
        cursor.insertText(" " + words)

    @staticmethod
    def saved(library: str, asset_id: str) -> str:
        """The text of the comment of `asset_id`, as it is on disk in `library`."""
        pages = guard.Guard(library).read(MATERIALS).document.get(notes.SECTION) or {}
        items = (pages.get(asset_id) or {}).get("items", [])
        return " ".join(" ".join(item.get("text", "") for item in items).split())

    def test_cm10_what_is_typed_is_saved_at_once_to_where_it_was_typed(self):
        first, pane, state = self.panel.pane.prefs.dir, self.panel.pane, self.panel.state
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
        self.panel.hide()
        self.assertEqual("three four", self.saved(first, GLASS), "lost by a rename or a hide")
        self.panel.show()
        self.type("five")
        state.showComments(False)
        self.assertEqual("three four five", self.saved(first, GLASS), "lost when closed")
        comments = self.panel.pane.comments
        self.assertTrue(_app.aboutToQuit.disconnect(comments.flush), "nothing saves at quit")
        state.showComments(True)
        QtWidgets.QApplication.processEvents()
        self.type("six")
        comments.flush()    # what quitting calls; no timer fires after it
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
