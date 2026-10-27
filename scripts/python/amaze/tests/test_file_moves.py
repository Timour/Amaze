"""Files moved between folders on disk, and what Amaze keeps about each. ▸r/cross-volume-move"""

import errno
import os
import shutil
import tempfile
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from amaze import messages  # noqa: E402
from amaze.core import captures, debug, file_library, file_moves  # noqa: E402
from amaze.core import keyed_store, notes, texture_library, thumbnails, tile_icons  # noqa: E402
from amaze.core import locations as locations_mod  # noqa: E402
from amaze.panel import sidebar  # noqa: E402
from amaze.tests import test_support  # noqa: E402
from amaze.tests.test_file_section import _Prefs, _pump_until  # noqa: E402
from amaze.tests.test_folder_tree import _child, _shown  # noqa: E402

OTHER_USER = "a1b2c3d4e5f60718293a4b5c6d7e8f90"    # a second minted-shaped uid
ICON = {"name": "activity", "bg": "#ff8000"}


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _picture(colour):
    image = QtGui.QImage(8, 8, QtGui.QImage.Format.Format_RGB32)
    image.fill(QtGui.QColor(colour))
    return image


GEO_CACHE = dict(prefix="geo_thumbnails_hiddenlineghost_black",
                 failure_tag=file_library.GEO_FAILURE_TAG)    # the one `_Prefs` points the grid at


class _Folders(unittest.TestCase):
    """Two folders under one scratch root, `a` holding plate.exr."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="amaze_move_")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.a = os.path.join(self.root, "a")
        self.b = os.path.join(self.root, "b")
        self.plate = os.path.join(self.a, "plate.exr")
        _write(self.plate, "plate")
        os.makedirs(self.b)
        self.landed = os.path.join(self.b, "plate.exr")

    def _move(self, **kwargs):
        return file_moves.move(file_moves.targets([self.plate], self.b), **kwargs)

    def _parts(self):
        return [name for name in os.listdir(self.b) if name.endswith(file_moves.PART)]


class AFileMovesOnOneDriveTest(_Folders):

    def test_the_file_lands_in_the_folder_and_leaves_its_old_place(self):
        result = self._move()
        self.assertEqual([(self.plate, self.landed)], result.moved)
        self.assertFalse(os.path.exists(self.plate))
        self.assertEqual("plate", _read(self.landed))

    def test_a_taken_name_is_skipped_and_both_files_are_kept(self):
        _write(self.landed, "other")
        result = self._move()
        self.assertEqual(([], [(self.plate, self.landed)]), (result.moved, result.skipped))
        self.assertEqual(("plate", "other"), (_read(self.plate), _read(self.landed)))

    def test_a_file_already_in_the_folder_is_no_target(self):
        self.assertEqual([], file_moves.targets([self.plate], self.a))

    def test_without_hard_links_a_taken_name_is_still_refused(self):
        """No hard links means a rename, which replaces silently. ▸r/cross-volume-move"""
        _write(self.landed, "other")
        with mock.patch.object(os, "link", side_effect=PermissionError(errno.EPERM, "no links")):
            result = self._move()
        self.assertEqual([(self.plate, self.landed)], result.skipped)
        self.assertEqual(("plate", "other"), (_read(self.plate), _read(self.landed)))

    def test_without_hard_links_a_free_name_still_moves(self):
        with mock.patch.object(os, "link", side_effect=PermissionError(errno.EPERM, "no links")):
            result = self._move()
        self.assertEqual([(self.plate, self.landed)], result.moved)
        self.assertFalse(os.path.exists(self.plate))


class AFileCopiesAcrossDrivesTest(_Folders):
    """`same_drive` answers no, so every file takes the copy door."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(file_moves, "same_drive", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_copy_lands_whole_and_the_original_goes(self):
        ticks = []
        result = self._move(tick=ticks.append)
        self.assertEqual([(self.plate, self.landed)], result.moved)
        self.assertEqual("plate", _read(self.landed))
        self.assertFalse(os.path.exists(self.plate))
        self.assertEqual(len("plate"), sum(ticks), "progress missed bytes")
        self.assertEqual([], self._parts())

    def test_a_copy_that_fails_keeps_the_original_and_leaves_no_part(self):
        full = OSError(errno.ENOSPC, "No space left on device")
        with mock.patch.object(os, "fsync", side_effect=full):
            result = self._move()
        self.assertEqual([(self.plate, "No space left on device")], result.failed)
        self.assertEqual("plate", _read(self.plate))
        self.assertFalse(os.path.exists(self.landed))
        self.assertEqual([], self._parts())

    def test_a_name_taken_while_copying_keeps_both_files(self):
        real_place = file_moves.place

        def taken(source, dest):
            _write(dest, "other")    # another hand got there first
            return real_place(source, dest)

        with mock.patch.object(file_moves, "place", side_effect=taken):
            result = self._move()
        self.assertEqual([(self.plate, self.landed)], result.skipped)
        self.assertEqual(("plate", "other"), (_read(self.plate), _read(self.landed)))
        self.assertEqual([], self._parts())

    def test_a_stop_mid_copy_keeps_the_original_and_leaves_no_part(self):
        ticks = []
        with mock.patch.object(file_moves, "CHUNK", 2):
            result = self._move(tick=ticks.append, stopped=lambda: bool(ticks))
        self.assertEqual([], result.moved)
        self.assertEqual("plate", _read(self.plate))
        self.assertFalse(os.path.exists(self.landed))
        self.assertEqual([], self._parts())


class WhatAmazeKeepsFollowsTheFileTest(unittest.TestCase):
    """Star, comment, icon and capture are filed by the file's key; a move re-files them."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="amaze_move_state_")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.a = os.path.join(self.root, "a")
        self.b = os.path.join(self.root, "b")
        self.plate = os.path.join(self.a, "plate.exr")
        _write(self.plate, "plate")
        os.makedirs(self.b)
        self.landed = os.path.join(self.b, "plate.exr")
        locations_mod.forget()
        self.addCleanup(locations_mod.forget)
        self.prefs = _Prefs([self.root])    # one location over both folders
        self.addCleanup(shutil.rmtree, self.prefs.dir, True)

    def _annotate(self):
        model = file_library.FileFiles(self.prefs)
        model.set_folder(self.a)
        names = [model.data(model.index(row, 0)) for row in range(model.rowCount())]
        row = names.index("plate.exr")
        key = model.file_key(row)
        model.toggle_favorite(row)
        model.set_tile_icon(row, ICON)
        notes.set_note(self.prefs, notes.note_key("file", key),
                       [{"t": "text", "text": "kept"}])
        _write(captures.file_path(self.prefs, key), "png")
        return model, row, key

    def _moved(self):
        result = file_moves.move(file_moves.targets([self.plate], self.b))
        file_moves.carry(self.prefs, result.moved)
        return captures.file_key(self.prefs, self.landed)

    def _kept(self, key):
        return (locations_mod.is_favourite(self.prefs, key),
                notes.has_note(self.prefs, notes.note_key("file", key)),
                bool(tile_icons.override_for(self.prefs, key)),
                captures.exists(captures.file_path(self.prefs, key)))

    def test_star_comment_icon_and_capture_follow_the_file(self):
        _model, _row, old = self._annotate()
        new = self._moved()
        self.assertNotEqual(old, new, "premise: the key does not name the folder")
        self.assertEqual((True, True, True, True), self._kept(new))
        self.assertEqual((False, False, False, False), self._kept(old))

    def test_another_users_star_follows_too(self):
        model, row, old = self._annotate()
        self.prefs.library_user = OTHER_USER
        model.toggle_favorite(row)
        self.prefs.library_user = test_support.FIXTURE_USER
        new = self._moved()
        spec = keyed_store.store_for(keyed_store.FAVOURITES)
        stored = keyed_store.open_store(spec, self.prefs).everyones()
        self.assertIn(OTHER_USER + keyed_store.USER_SEP + new, stored)
        self.assertNotIn(OTHER_USER + keyed_store.USER_SEP + old, stored)

    def test_an_entry_left_at_the_new_place_yields_to_the_file_arriving(self):
        self._annotate()
        stale = captures.file_key(self.prefs, self.landed)
        notes.set_note(self.prefs, notes.note_key("file", stale),
                       [{"t": "text", "text": "stale"}])
        new = self._moved()
        page = notes.note_for(self.prefs, notes.note_key("file", new))
        self.assertEqual("kept", page["items"][0]["text"])


class ThePicturesFollowTheFileTest(unittest.TestCase):
    """A moved file's cached pictures follow it: nothing renders again, nothing stays behind."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="amaze_move_thumbs_")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.a = os.path.join(self.root, "a")
        self.b = os.path.join(self.root, "b")
        os.makedirs(self.b)
        self.plate = os.path.join(self.a, "plate.exr")
        self.mesh = os.path.join(self.a, "mesh.obj")
        _write(self.plate, "plate")
        _write(self.mesh, "v 0 0 0")
        locations_mod.forget()
        self.addCleanup(locations_mod.forget)
        self.prefs = _Prefs([self.root])
        self.addCleanup(shutil.rmtree, self.prefs.dir, True)
        self.images = texture_library.ThumbnailCache(256)
        self.geo = texture_library.ThumbnailCache(256, **GEO_CACHE)
        self.images.put(self.plate, _picture("#d08040"))
        self.geo.put(self.mesh, _picture("#40d080"))
        self.images.save()
        self.geo.save()

    def _move(self, sources, folder=None):
        result = file_moves.move(file_moves.targets(sources, folder or self.b))
        file_moves.carry(self.prefs, result.moved)
        return result.moved

    def _on_disk(self, cache):
        """What the cache's manifest file says, read fresh, as the next session will."""
        kwargs = GEO_CACHE if cache is self.geo else {}
        return texture_library.ThumbnailCache(cache.size, **kwargs)

    def test_a_moved_files_pictures_follow_it_and_leave_nothing_behind(self):
        self._move([self.plate, self.mesh])
        for cache, old in ((self.images, self.plate), (self.geo, self.mesh)):
            new = os.path.join(self.b, os.path.basename(old))
            for reader in (cache, self._on_disk(cache)):
                with self.subTest(cache=cache.cache_dir, reader=reader is cache):
                    self.assertIsNotNone(reader.valid_path(new), "the picture did not follow")
                    self.assertIsNone(reader.valid_path(old), "an entry stayed behind")
            gone = os.path.join(cache.cache_dir, texture_library.ThumbnailCache._cache_filename(
                texture_library.ThumbnailCache._key(old)))
            self.assertFalse(os.path.exists(gone), "the old picture file stayed behind")

    def test_the_open_caches_do_not_write_the_old_entry_back(self):
        self._move([self.plate])
        self.images._dirty = True
        self.images.save()
        held = self._on_disk(self.images).paths()
        self.assertNotIn(texture_library.ThumbnailCache._key(self.plate), held)
        self.assertIn(texture_library.ThumbnailCache._key(os.path.join(self.b, "plate.exr")), held)

    def test_a_picture_left_at_the_new_place_yields_to_the_file_arriving(self):
        stale = os.path.join(self.b, "plate.exr")
        _write(stale, "an older file of that name")
        self.images.put(stale, _picture("#2040ff"))
        self.images.save()
        os.remove(stale)    # that file left; its picture stayed
        self._move([self.plate])
        png = self.images.valid_path(stale)
        self.assertIsNotNone(png, "the arriving file has no picture")
        self.assertEqual("#d08040", QtGui.QImage(png).pixelColor(1, 1).name())

    def test_a_picture_not_yet_saved_follows_too(self):
        fresh = os.path.join(self.a, "fresh.exr")
        _write(fresh, "fresh")
        self.images.put(fresh, _picture("#80c040"))    # made, and not in the manifest file yet
        self._move([fresh])
        landed = os.path.join(self.b, "fresh.exr")
        self.assertIsNotNone(self._on_disk(self.images).valid_path(landed),
                             "a picture the grid had not saved stayed behind")

    def test_the_grids_copy_of_an_old_picture_is_dropped(self):
        landed = texture_library.ThumbnailCache._key(os.path.join(self.b, "plate.exr"))
        stale = ("tex", landed, self.images.size)    # the key the grid paints that row by
        thumbnails.engine.deposit(stale, _picture("#2040ff"))
        self.addCleanup(thumbnails.engine.discard, stale)
        self._move([self.plate])
        self.assertIsNone(thumbnails.engine.peek(stale), "the grid would paint a stale copy")

    def test_undo_brings_back_the_picture_the_file_has_now(self):
        """Not the stale one its old place kept - the one 1.19.0 showed after a move back."""
        moved = self._move([self.plate])
        landed = os.path.join(self.b, "plate.exr")
        self.images.put(landed, _picture("#2040ff"))    # made again where it landed
        self.images.save()
        back = file_moves.move(file_moves.back(moved))
        file_moves.carry(self.prefs, back.moved)
        png = self.images.valid_path(self.plate)
        self.assertIsNotNone(png, "the file came back without a picture")
        self.assertEqual("#2040ff", QtGui.QImage(png).pixelColor(1, 1).name(),
                         "the old place's stale picture came back")
        self.assertIsNone(self.images.valid_path(landed))

    def test_a_hundred_moved_files_render_nothing(self):
        meshes = []
        for at in range(100):
            path = os.path.join(self.a, "m%03d.obj" % at)
            _write(path, "v %d 0 0" % at)
            self.geo.put(path, _picture("#40d080"))
            meshes.append(path)
        self.geo.save()
        self._move(meshes)
        model = file_library.FileFiles(self.prefs)
        asked = []
        model.render_geo = asked.extend
        model.set_folder(self.b)
        listed = [model.data(model.index(row, 0)) for row in range(model.rowCount())]
        self.assertEqual(100, sum(1 for name in listed if name.startswith("m")))
        self.assertEqual([], asked, "moved files were sent to render again")


class TheFileTabMovesWhatLandsOnAFolderTest(unittest.TestCase):
    """A release over a folder row moves the selected files there; Undo Move puts them back."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.said = []
        previous = debug._ui
        debug.hand_over(types.SimpleNamespace(status=self.said.append,
                                              dialog=self.said.append))
        self.addCleanup(debug.hand_over, previous)
        self.folders = self.panel.file_folders_model
        self.loc = self.folders.data(self.folders.index(1, 0), self.folders.PathRole)
        self.a, self.b = _child(self.loc, "a"), _child(self.loc, "b")
        self.plate = os.path.join(self.a, "plate.exr")
        self.landed = os.path.join(self.b, "plate.exr")
        _write(self.plate, "plate")
        os.makedirs(self.b)
        self.panel.section_tabs.setChecked("file")
        QtWidgets.QApplication.processEvents()
        self.section = self.panel.sections["file"]
        _shown(self.folders, self.loc)
        self.assertTrue(_pump_until(
            lambda: self.folders.index_of(self.b).isValid()),
            "premise: the subfolders never arrived")
        self.section._browse(self.a)
        self.assertTrue(_pump_until(lambda: self._tile("plate.exr") is not None),
                        "premise: plate.exr never listed")

    def _tile(self, name):
        proxy = self.panel.file_sorted_model
        for row in range(proxy.rowCount()):
            index = proxy.index(row, 0)
            if index.data() == name:
                return index
        return None

    def _release_over(self, folder):
        tile = self._tile("plate.exr")
        self.panel.file_selection_model.select(
            tile, QtCore.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        view = self.panel.thumblist
        view._dragging = True
        view._drag_panel = self.panel
        view._drag_section = "file"
        view._drag_index = tile
        release = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseButtonRelease, QtCore.QPointF(5, 5),
            QtCore.QPointF(5, 5), QtCore.QPointF(5, 5),
            QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.MouseButton.LeftButton,
            QtCore.Qt.KeyboardModifier.NoModifier)
        with mock.patch.object(self.panel, "_category_under_cursor", return_value=None), \
                mock.patch.object(self.panel, "_folder_under_cursor", return_value=folder):
            view._release(release)
        self.assertTrue(_pump_until(lambda: not file_moves.mover.busy()),
                        "the move never finished")
        QtWidgets.QApplication.processEvents()

    def test_a_release_over_a_folder_moves_the_selection_there(self):
        self._release_over(self.b)
        self.assertEqual("plate", _read(self.landed))
        self.assertFalse(os.path.exists(self.plate))
        self.assertTrue(_pump_until(lambda: self._tile("plate.exr") is None),
                        "the moved file is still listed where it was")
        self.assertEqual(messages.MOVE_DONE % ("1 file", "b"), self.said[-1])

    def test_the_release_carries_the_files_picture(self):
        cache = self.panel.file_files_model._get_image_cache()
        cache.put(self.plate, _picture("#d08040"))
        cache.save()
        self._release_over(self.b)
        held = texture_library.ThumbnailCache(cache.size).paths()
        self.assertIn(texture_library.ThumbnailCache._key(self.landed), held)
        self.assertNotIn(texture_library.ThumbnailCache._key(self.plate), held)

    def test_undo_move_puts_the_file_back(self):
        self.assertFalse(self.section.can_undo_move([], None), "premise: nothing to undo yet")
        self._release_over(self.b)
        self.assertTrue(self.section.can_undo_move([], None), "Undo Move is not offered")
        self.section.menu_undo_move([], None)
        self.assertTrue(_pump_until(lambda: not file_moves.mover.busy()))
        QtWidgets.QApplication.processEvents()
        self.assertEqual("plate", _read(self.plate))
        self.assertFalse(os.path.exists(self.landed))
        self.assertEqual(messages.MOVE_BACK % "1 file", self.said[-1])
        self.assertFalse(self.section.can_undo_move([], None), "an undone move undoes again")

    def test_a_taken_name_is_named_on_the_status_line(self):
        _write(self.landed, "other")
        self._release_over(self.b)
        self.assertEqual(("plate", "other"), (_read(self.plate), _read(self.landed)))
        self.assertEqual(messages.MOVE_TAKEN % ("plate.exr", "b"), self.said[-1])
        self.assertFalse(self.section.can_undo_move([], None), "nothing moved, yet Undo is offered")

    def test_more_than_three_taken_names_end_in_a_count(self):
        names = ("1.exr", "2.exr", "3.exr", "4.exr", "5.exr")
        skipped = [(os.path.join(self.a, n), os.path.join(self.b, n)) for n in names]
        self.assertEqual(
            [messages.MOVE_TAKEN_MANY % ("1.exr, 2.exr, 3.exr and 2 more", "b")],
            self.section._taken_lines(skipped))

    def test_hovering_a_subfolder_lights_that_row_only(self):
        """Rows are numbered per parent in a tree, so the highlight holds the row itself."""
        view = self.panel.cat_list
        view.expand(self.folders.index_of(self.loc))
        QtWidgets.QApplication.processEvents()
        target = self.folders.index_of(self.b)
        sidebar.update_hover(self.panel, view.visualRect(target).center())
        delegate = self.panel.sidebar_delegate
        lit = []
        for row in range(self.folders.rowCount()):
            top = self.folders.index(row, 0)
            for index in [top] + [self.folders.index(r, 0, top)
                                  for r in range(self.folders.rowCount(top))]:
                if delegate.drop_target(index):
                    lit.append(index.data(self.folders.BrowseRole))
        self.assertEqual([self.b], lit)
        sidebar.set_hover_row(self.panel, -1)
        self.assertFalse(delegate.drop_target(target), "-1 left the row lit")

    def test_all_takes_no_drop_and_asset_tabs_take_no_file_drop(self):
        view = self.panel.cat_list
        all_row = self.folders.index(0, 0)
        self.assertIsNone(sidebar.folder_at_point(
            self.panel, view.visualRect(all_row).center()))
        self.assertEqual(self.loc, sidebar.folder_at_point(
            self.panel, view.visualRect(self.folders.index(1, 0)).center()))
        self.panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        self.assertIsNone(sidebar.folder_under_cursor(self.panel))
        self.assertFalse(self.panel.sections["material"].takes_file_drops)


if __name__ == "__main__":
    unittest.main()
