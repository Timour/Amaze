"""Moving files between folders on disk, and what Amaze stores for each. ▸r/cross-volume-move"""

import contextlib
import errno
import importlib
import os
import shutil
import stat
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from amaze import messages  # noqa: E402
from amaze.core import captures, debug, file_library, file_moves  # noqa: E402
from amaze.pane import files as pane_files  # noqa: E402
from amaze.core import guard, library_db, notes, texture_library, thumbnails, tile_icons  # noqa: E402
from amaze.core import workers  # noqa: E402
from amaze.core import locations as locations_mod  # noqa: E402
import hou  # noqa: E402
from amaze.helpers import hostos  # noqa: E402
from amaze.panel import sidebar  # noqa: E402
from amaze.tests import test_support  # noqa: E402
from amaze.tests.test_file_section import _Prefs  # noqa: E402
from amaze.tests.test_folder_tree import _child, _shown  # noqa: E402

OTHER_USER = "a1b2c3d4e5f60718293a4b5c6d7e8f90"    # a second minted-shaped uid
ICON = {"name": "activity", "bg": "#ff8000"}


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _picture(colour):
    image = QtGui.QImage(8, 8, QtGui.QImage.Format.Format_RGB32)
    image.fill(QtGui.QColor(colour))
    return image


GEO_CACHE = dict(prefix="geo_thumbnails_hiddenlineghost_black",
                 failure_tag=file_library.GEO_FAILURE_TAG)    # the cache `_Prefs` sets


def _writable(path):
    """Clear a read-only flag so cleanup can delete the file - Windows refuses otherwise."""
    try:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    except OSError:
        pass


@contextlib.contextmanager
def _written_first(dest):
    """Patch the renames so another program's file is written at `dest` just before each one."""
    def first(real):
        def call(source, target, *args, **kwargs):
            if target == dest and not os.path.lexists(dest):
                test_support.write_text(dest, "other")
            return real(source, target, *args, **kwargs)
        return call

    with mock.patch.object(os, "rename", first(os.rename)), \
            mock.patch.object(hostos, "rename_exclusive", first(hostos.rename_exclusive)):
        yield


NO_LINKS = PermissionError(errno.EPERM, "no links")    # the error a drive without hard links raises


class _Folders(unittest.TestCase):
    """Two folders under one scratch root, `a` holding plate.exr."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="amaze_move_")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.a = os.path.join(self.root, "a")
        self.b = os.path.join(self.root, "b")
        self.plate = os.path.join(self.a, "plate.exr")
        test_support.write_text(self.plate, "plate")
        os.makedirs(self.b)
        self.moved_to = os.path.join(self.b, "plate.exr")

    def _move(self, **kwargs):
        return file_moves.move(file_moves.targets([self.plate], self.b), **kwargs)

    def _parts(self):
        return [name for name in os.listdir(self.b) if name.endswith(file_moves.PART)]


class AFileMovesOnOneDriveTest(_Folders):

    def test_the_file_moves_into_the_folder_and_leaves_its_old_place(self):
        result = self._move()
        self.assertEqual([(self.plate, self.moved_to)], result.moved)
        self.assertFalse(os.path.exists(self.plate))
        self.assertEqual("plate", _read(self.moved_to))

    def test_a_taken_name_is_skipped_and_both_files_are_kept(self):
        test_support.write_text(self.moved_to, "other")
        result = self._move()
        self.assertEqual(([], [(self.plate, self.moved_to)]), (result.moved, result.skipped))
        self.assertEqual(("plate", "other"), (_read(self.plate), _read(self.moved_to)))

    def test_a_file_already_in_the_folder_is_no_target(self):
        self.assertEqual([], file_moves.targets([self.plate], self.a))

    @unittest.skipUnless(sys.platform == "win32", "only Windows refuses to rename a file held open")
    def test_a_file_held_for_a_moment_still_moves(self):
        """A thumbnail read keeps the file open briefly; Windows fails the rename until it closes."""
        holder = open(self.plate, "rb")
        threading.Timer(0.1, holder.close).start()
        result = self._move()
        holder.close()
        self.assertEqual([(self.plate, self.moved_to)], result.moved,
                         "a file open for only 0.1 s failed the move: %s" % (result.failed,))
        self.assertEqual("plate", _read(self.moved_to))

    @unittest.skipUnless(sys.platform == "win32", "only Windows refuses to rename a file held open")
    def test_a_file_held_for_good_fails_and_stays(self):
        with open(self.plate, "rb"):
            result = self._move()
        self.assertEqual([self.plate], [source for source, _why in result.failed])
        self.assertEqual("plate", _read(self.plate))
        self.assertFalse(os.path.exists(self.moved_to))

    def test_without_hard_links_a_taken_name_is_still_skipped(self):
        """A plain rename replaces silently, so the move never uses one. ▸r/no-replace-rename"""
        test_support.write_text(self.moved_to, "other")
        with mock.patch.object(os, "link", side_effect=NO_LINKS):
            result = self._move()
        self.assertEqual([(self.plate, self.moved_to)], result.skipped)
        self.assertEqual(("plate", "other"), (_read(self.plate), _read(self.moved_to)))

    def test_without_hard_links_a_free_name_still_moves(self):
        with mock.patch.object(os, "link", side_effect=NO_LINKS):
            result = self._move()
        self.assertEqual([(self.plate, self.moved_to)], result.moved)
        self.assertFalse(os.path.exists(self.plate))

    def test_a_name_taken_in_the_last_instant_is_kept(self):
        """Another program writes the name after every check, just before the rename. ▸r/no-replace-rename"""
        with mock.patch.object(os, "link", side_effect=NO_LINKS), _written_first(self.moved_to):
            result = self._move()
        self.assertEqual([(self.plate, self.moved_to)], result.skipped,
                         "the move replaced a file written under its name: %s" % (result,))
        self.assertEqual(("plate", "other"), (_read(self.plate), _read(self.moved_to)))

    def test_a_rename_failing_across_mounts_still_moves_by_copy(self):
        """One st_dev can be two mounts: a bind mount fails the rename with EXDEV. ▸r/cross-volume-move"""
        def across(real):
            def call(source, dest, *args, **kwargs):
                if os.path.dirname(source) != os.path.dirname(dest):
                    raise OSError(errno.EXDEV, os.strerror(errno.EXDEV))
                return real(source, dest, *args, **kwargs)
            return call

        with mock.patch.object(os, "link", across(os.link)), \
                mock.patch.object(os, "rename", across(os.rename)), \
                mock.patch.object(hostos, "rename_exclusive", across(hostos.rename_exclusive)):
            result = self._move()
        self.assertEqual([(self.plate, self.moved_to)], result.moved,
                         "a rename failing with EXDEV failed the move: %s" % (result.failed,))
        self.assertFalse(os.path.exists(self.plate))
        self.assertEqual("plate", _read(self.moved_to))


class AFileCopiesAcrossDrivesTest(_Folders):
    """`same_drive` is patched to return False, so every file is moved by `copy_across`."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(file_moves, "same_drive", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_copy_is_complete_and_the_original_is_removed(self):
        ticks = []
        result = self._move(tick=ticks.append)
        self.assertEqual([(self.plate, self.moved_to)], result.moved)
        self.assertEqual("plate", _read(self.moved_to))
        self.assertFalse(os.path.exists(self.plate))
        self.assertEqual(len("plate"), sum(ticks), "progress missed bytes")
        self.assertEqual([], self._parts())

    def test_a_copy_that_fails_keeps_the_original_and_leaves_no_part(self):
        full = OSError(errno.ENOSPC, "No space left on device")
        with mock.patch.object(os, "fsync", side_effect=full):
            result = self._move()
        self.assertEqual([(self.plate, "No space left on device")], result.failed)
        self.assertEqual("plate", _read(self.plate))
        self.assertFalse(os.path.exists(self.moved_to))
        self.assertEqual([], self._parts())

    def test_a_name_taken_while_copying_keeps_both_files(self):
        real_place = file_moves.place

        def taken(source, dest):
            test_support.write_text(dest, "other")    # another program wrote the name first
            return real_place(source, dest)

        with mock.patch.object(file_moves, "place", side_effect=taken):
            result = self._move()
        self.assertEqual([(self.plate, self.moved_to)], result.skipped)
        self.assertEqual(("plate", "other"), (_read(self.plate), _read(self.moved_to)))
        self.assertEqual([], self._parts())

    def test_a_name_taken_as_the_copy_finishes_keeps_both_files(self):
        """The copy is renamed into place by `place`, after its own check. ▸r/no-replace-rename"""
        with mock.patch.object(os, "link", side_effect=NO_LINKS), _written_first(self.moved_to):
            result = self._move()
        self.assertEqual([(self.plate, self.moved_to)], result.skipped,
                         "the copy replaced a file written under its name: %s" % (result,))
        self.assertEqual(("plate", "other"), (_read(self.plate), _read(self.moved_to)))
        self.assertEqual([], self._parts())

    def test_a_read_only_original_still_goes(self):
        """POSIX deletes a read-only file from a writable folder; Windows refuses until the flag is off."""
        os.chmod(self.plate, stat.S_IREAD)
        self.addCleanup(_writable, self.plate)
        self.addCleanup(_writable, self.moved_to)
        result = self._move()
        self.assertEqual([(self.plate, self.moved_to)], result.moved,
                         "a read-only file was copied and its original kept")
        self.assertFalse(os.path.exists(self.plate))
        self.assertEqual("plate", _read(self.moved_to))
        self.assertFalse(os.stat(self.moved_to).st_mode & stat.S_IWRITE,
                         "the moved file lost its read-only flag")

    @unittest.skipUnless(sys.platform == "win32", "only Windows refuses to delete a file held open")
    def test_an_original_held_open_is_not_copied(self):
        """A file another program has open cannot be deleted on Windows, so a copy leaves two files."""
        with open(self.plate, "rb"):
            result = self._move()
        self.assertEqual([], result.moved)
        self.assertEqual([self.plate], [source for source, _why in result.failed])
        self.assertEqual("plate", _read(self.plate))
        self.assertFalse(os.path.exists(self.moved_to), "the open file was copied anyway")
        self.assertEqual([], self._parts())

    def test_a_stop_mid_copy_keeps_the_original_and_leaves_no_part(self):
        ticks = []
        with mock.patch.object(file_moves, "CHUNK", 2):
            result = self._move(tick=ticks.append, stopped=lambda: bool(ticks))
        self.assertEqual([], result.moved)
        self.assertEqual("plate", _read(self.plate))
        self.assertFalse(os.path.exists(self.moved_to))
        self.assertEqual([], self._parts())

    def test_a_part_left_by_an_earlier_copy_blocks_nothing(self):
        """Quitting Houdini mid-copy, or a crash, leaves a part file; the target name is free."""
        left = "." + os.path.basename(self.moved_to) + file_moves.PART
        test_support.write_text(os.path.join(self.b, left), "half")
        result = self._move()
        self.assertEqual([(self.plate, self.moved_to)], result.moved,
                         "an earlier copy's part file stopped the move: %s" % (result.failed,))
        self.assertEqual("plate", _read(self.moved_to))
        self.assertEqual([left], self._parts(), "this copy left a part of its own")

    def test_a_part_file_that_cannot_be_deleted_is_logged(self):
        real_unlink = os.unlink

        def held(path, *args, **kwargs):    # Windows failing to delete a read-only part, any OS
            if str(path).endswith(file_moves.PART):
                raise PermissionError(errno.EACCES, "Permission denied", str(path))
            return real_unlink(path, *args, **kwargs)

        with test_support.captured_log() as log, \
                mock.patch.object(os, "fsync", side_effect=OSError(errno.ENOSPC, "full")), \
                mock.patch.object(os, "unlink", held):
            result = self._move()
        self.assertEqual([self.plate], [source for source, _why in result.failed],
                         "premise: the copy did not fail")
        logged = [record for record in log.records("move")
                  if str(record.get("data", {}).get("file", "")).endswith(file_moves.PART)]
        self.assertTrue(logged, "a part file the copy could not remove was not logged")


class TheExclusiveRenameTest(_Folders):
    """`hostos.rename_exclusive`, the one rename a move uses, and its no-replace flag."""

    def test_a_taken_name_returns_false_and_both_files_are_kept(self):
        test_support.write_text(self.moved_to, "other")
        self.assertFalse(hostos.rename_exclusive(self.plate, self.moved_to))
        self.assertEqual(("plate", "other"), (_read(self.plate), _read(self.moved_to)))

    def test_a_free_name_is_renamed(self):
        self.assertTrue(hostos.rename_exclusive(self.plate, self.moved_to))
        self.assertFalse(os.path.exists(self.plate))
        self.assertEqual("plate", _read(self.moved_to))

    @unittest.skipIf(sys.platform == "win32", "Windows renames with a call that takes no flag")
    def test_a_drive_without_the_flag_raises_no_exclusive_rename_and_renames_nothing(self):
        with mock.patch.object(hostos, "_flagged_rename", return_value=errno.ENOTSUP), \
                self.assertRaises(hostos.NoExclusiveRename):
            hostos.rename_exclusive(self.plate, self.moved_to)
        self.assertEqual("plate", _read(self.plate))
        self.assertFalse(os.path.exists(self.moved_to))

    @unittest.skipIf(sys.platform == "win32", "Windows renames with a call that takes no flag")
    def test_any_other_os_error_is_raised_as_itself(self):
        with mock.patch.object(hostos, "_flagged_rename", return_value=errno.EXDEV), \
                self.assertRaises(OSError) as caught:
            hostos.rename_exclusive(self.plate, self.moved_to)
        self.assertEqual(errno.EXDEV, caught.exception.errno)
        self.assertNotIsInstance(caught.exception, hostos.NoExclusiveRename)


@unittest.skipIf(sys.platform == "win32", "the Windows rename refuses a taken name, so it never claims")
class ADriveWithNoSafeRenameTest(_Folders):
    """exFAT, FAT32 and a share on a Mac: `_claimed` creates an empty file at the name first."""

    def setUp(self):
        super().setUp()
        unsupported = hostos.NoExclusiveRename(errno.ENOTSUP, "no flag")
        for patcher in (mock.patch.object(hostos, "rename_exclusive", side_effect=unsupported),
                        mock.patch.object(os, "link", side_effect=NO_LINKS)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _rename_with(self, before):
        real = os.rename

        def rename(source, dest, *args, **kwargs):
            before(dest)
            return real(source, dest, *args, **kwargs)
        return mock.patch.object(os, "rename", rename)

    def test_a_free_name_still_moves(self):
        result = self._move()
        self.assertEqual([(self.plate, self.moved_to)], result.moved, result.failed)
        self.assertFalse(os.path.exists(self.plate))
        self.assertEqual("plate", _read(self.moved_to))

    def test_a_taken_name_is_still_skipped(self):
        test_support.write_text(self.moved_to, "other")
        result = self._move()
        self.assertEqual([(self.plate, self.moved_to)], result.skipped)
        self.assertEqual(("plate", "other"), (_read(self.plate), _read(self.moved_to)))

    def test_the_claim_holds_the_name_until_the_rename(self):
        """A program creating the name after the empty file exists fails. ▸r/no-replace-rename"""
        failed_creates = []

        def create(dest):
            try:
                os.close(os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL))
            except FileExistsError:
                failed_creates.append(dest)

        with self._rename_with(create):
            result = self._move()
        self.assertEqual([self.moved_to], failed_creates, "the name was free just before the rename")
        self.assertEqual([(self.plate, self.moved_to)], result.moved, result.failed)
        self.assertEqual("plate", _read(self.moved_to))

    def test_a_failed_rename_takes_its_claim_back(self):
        with mock.patch.object(os, "rename", side_effect=PermissionError(errno.EACCES, "denied")):
            result = self._move()
        self.assertEqual([self.plate], [source for source, _why in result.failed])
        self.assertEqual("plate", _read(self.plate))
        self.assertFalse(os.path.lexists(self.moved_to), "the empty file `_claimed` made was left")

    def test_a_claim_written_into_is_left_alone(self):
        """A program that wrote into the empty file keeps its file when the rename then fails."""
        def overwrite(dest):
            test_support.write_text(dest, "other")
            raise PermissionError(errno.EACCES, "denied")

        with self._rename_with(overwrite):
            result = self._move()
        self.assertEqual([self.plate], [source for source, _why in result.failed])
        self.assertEqual(("plate", "other"), (_read(self.plate), _read(self.moved_to)))

    def test_a_name_a_share_gave_away_is_skipped(self):
        """A share deletes the empty file to rename, and another machine took the name meanwhile."""
        with mock.patch.object(os, "rename", side_effect=FileExistsError(errno.EEXIST, "taken")):
            result = self._move()
        self.assertEqual([(self.plate, self.moved_to)], result.skipped)
        self.assertEqual("plate", _read(self.plate))
        self.assertFalse(os.path.lexists(self.moved_to), "the empty file `_claimed` made was left")

    def test_a_copy_from_another_drive_moves_through_the_claim(self):
        with mock.patch.object(file_moves, "same_drive", return_value=False):
            result = self._move()
        self.assertEqual([(self.plate, self.moved_to)], result.moved, result.failed)
        self.assertFalse(os.path.exists(self.plate))
        self.assertEqual("plate", _read(self.moved_to))
        self.assertEqual([], self._parts())


def _blocking_move(entered, release):
    """A `move` that ignores `stopped` and cannot be terminated, like a copy on a hung share."""
    def move(pairs, tick=None, stopped=lambda: False):
        QtCore.QThread.setTerminationEnabled(False)    # so terminate() cannot end it either
        entered.set()
        release.wait(30)    # never calls stopped()
        return file_moves.Result([], [], [])
    return move


def _release_move(worker, release, ended):
    """Release a blocked move; drop it from `workers._unstoppable` once `finished` arrived."""
    release.set()
    if not test_support.pump_until(lambda: bool(ended), timeout=30):
        raise AssertionError("the held move never ended")
    if worker in workers._unstoppable:
        workers._unstoppable.remove(worker)


def _started(testcase, engine, finished=lambda result: None):
    """Start a blocked move on `engine`, released at cleanup; returns (worker, release event)."""
    entered, release, ended = threading.Event(), threading.Event(), []
    patcher = mock.patch.object(file_moves, "move", _blocking_move(entered, release))
    patcher.start()
    testcase.addCleanup(patcher.stop)
    testcase.assertTrue(engine.start([("/nowhere/a.exr", "/nowhere/b/a.exr")], None,
                                     lambda *tick: None, finished))
    worker = engine._worker
    worker.finished.connect(lambda: ended.append(True))
    testcase.addCleanup(_release_move, worker, release, ended)
    testcase.assertTrue(entered.wait(10), "premise: the move never started")
    return worker, release


class AMoveThatWillNotStopIsKeptInUnstoppableTest(unittest.TestCase):
    """A copy the OS cannot interrupt outlasts the quit's waits; dropped, it aborts as it ends."""

    def test_the_quit_keeps_a_move_that_ignores_its_stop_in_unstoppable(self):
        engine = file_moves._MoveEngine()
        worker, _release = _started(self, engine)
        started = time.monotonic()
        engine.shutdown()
        elapsed = time.monotonic() - started
        self.assertTrue(worker.isRunning(), "premise: the move stopped, so none was kept")
        self.assertIn(worker, workers._unstoppable,
                      "a running move was dropped - it aborts the process when it ends")
        bound = (workers.WAIT_MS + workers.TERMINATE_MS) / 1000.0 + 1.0
        self.assertLess(elapsed, bound, "the quit waited %.1fs on one move" % elapsed)


class AReloadLeavesAMoveUnderWayAloneTest(unittest.TestCase):
    """A reload keeps the engine a move runs on, so it finishes; an idle engine is replaced."""

    def test_a_busy_mover_is_kept_by_a_reload_and_an_idle_one_is_not(self):
        before, finished = file_moves.mover, []
        _worker, release = _started(self, before, finished.append)
        importlib.reload(file_moves)
        self.assertIs(before, file_moves.mover, "a reload replaced the engine running a move")
        release.set()
        self.assertTrue(test_support.pump_until(lambda: bool(finished) and not before.busy()),
                        "the running move never finished")
        importlib.reload(file_moves)
        self.assertIsNot(before, file_moves.mover, "a reload kept an idle engine")


class WhatAmazeKeepsFollowsTheFileTest(unittest.TestCase):
    """Star, comment, icon and capture are stored by the file's key; `rekey_moved_files` re-keys them."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="amaze_move_state_")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.a = os.path.join(self.root, "a")
        self.b = os.path.join(self.root, "b")
        self.plate = os.path.join(self.a, "plate.exr")
        test_support.write_text(self.plate, "plate")
        os.makedirs(self.b)
        self.moved_to = os.path.join(self.b, "plate.exr")
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
        test_support.write_text(captures.file_path(self.prefs, key), "png")
        return model, row, key

    def _moved(self):
        result = file_moves.move(file_moves.targets([self.plate], self.b))
        file_moves.rekey_moved_files(self.prefs, result.moved)
        return captures.file_key(self.prefs, self.moved_to)

    def _kept(self, key):
        return (locations_mod.is_favourite(self.prefs, key),
                notes.has_note(self.prefs, notes.note_key("file", key)),
                bool(tile_icons.override_for(self.prefs, key, locations_mod.FILES)),
                captures.exists(captures.file_path(self.prefs, key)))

    def test_star_comment_icon_and_capture_follow_the_file(self):
        _model, _row, old = self._annotate()
        new = self._moved()
        self.assertNotEqual(old, new, "premise: the key does not name the folder")
        self.assertEqual((True, True, True, True), self._kept(new))
        self.assertEqual((False, False, False, False), self._kept(old))

    def test_an_entry_left_at_the_new_place_is_replaced_by_the_moved_files_entry(self):
        self._annotate()
        stale = captures.file_key(self.prefs, self.moved_to)
        notes.set_note(self.prefs, notes.note_key("file", stale),
                       [{"t": "text", "text": "stale"}])
        new = self._moved()
        page = notes.note_for(self.prefs, notes.note_key("file", new))
        self.assertEqual("kept", page["items"][0]["text"])

    def test_a_failed_write_never_replaces_the_moved_comment_with_the_stale_one(self):
        """One write per store: a failed write moves nothing, never half."""
        _model, _row, old = self._annotate()
        stale = captures.file_key(self.prefs, self.moved_to)
        notes.set_note(self.prefs, notes.note_key("file", stale),
                       [{"t": "text", "text": "stale"}])
        real_write, failed_writes = guard.Disk.write, []

        def held_once(disk, path, data):    # one write failing, as on Windows
            if os.path.basename(path).startswith(locations_mod.FILES + ".") and not failed_writes:
                failed_writes.append(path)
                raise PermissionError(errno.EACCES, "held for a moment", path)
            return real_write(disk, path, data)

        with mock.patch.object(guard.Disk, "write", held_once), \
                mock.patch.object(library_db.debug, "alert"):
            new = self._moved()
        self.assertTrue(failed_writes, "premise: no write of the comments failed")
        self.assertEqual(stale, new, "premise: the moved file's key is the stale comment's key")
        texts = [(notes.note_for(self.prefs, notes.note_key("file", key)).get("items")
                  or [{}])[0].get("text") for key in (old, new)]
        self.assertIn("kept", texts,
                      "the moved file's comment is gone and the stale one shows in its "
                      "place: %s" % texts)


class ThePicturesFollowTheFileTest(unittest.TestCase):
    """A moved file's cached thumbnails are re-keyed: nothing renders again, no old entry stays."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="amaze_move_thumbs_")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.a = os.path.join(self.root, "a")
        self.b = os.path.join(self.root, "b")
        os.makedirs(self.b)
        self.plate = os.path.join(self.a, "plate.exr")
        self.mesh = os.path.join(self.a, "mesh.obj")
        test_support.write_text(self.plate, "plate")
        test_support.write_text(self.mesh, "v 0 0 0")
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
        file_moves.rekey_moved_files(self.prefs, result.moved)
        return result.moved

    def _on_disk(self, cache):
        """A new cache read from the manifest file, as the next session reads it."""
        kwargs = GEO_CACHE if cache is self.geo else {}
        return texture_library.ThumbnailCache(cache.size, **kwargs)

    def test_a_moved_files_pictures_follow_it_and_leave_nothing_behind(self):
        self._move([self.plate, self.mesh])
        for cache, old in ((self.images, self.plate), (self.geo, self.mesh)):
            new = os.path.join(self.b, os.path.basename(old))
            for reader in (cache, self._on_disk(cache)):
                with self.subTest(cache=cache.cache_dir, reader=reader is cache):
                    self.assertIsNotNone(reader.valid_path(new), "no thumbnail at the new path")
                    self.assertIsNone(reader.valid_path(old), "the old path's entry remains")
            gone = os.path.join(cache.cache_dir, texture_library.ThumbnailCache._cache_filename(
                texture_library.ThumbnailCache._key(old)))
            self.assertFalse(os.path.exists(gone), "the old thumbnail file was not deleted")

    def test_the_open_caches_do_not_write_the_old_entry_back(self):
        self._move([self.plate])
        self.images._dirty = True
        self.images.save()
        held = self._on_disk(self.images).paths()
        self.assertNotIn(texture_library.ThumbnailCache._key(self.plate), held)
        self.assertIn(texture_library.ThumbnailCache._key(os.path.join(self.b, "plate.exr")), held)

    def test_a_picture_left_at_the_new_place_is_replaced_by_the_moved_files_picture(self):
        stale = os.path.join(self.b, "plate.exr")
        test_support.write_text(stale, "an older file of that name")
        self.images.put(stale, _picture("#2040ff"))
        self.images.save()
        os.remove(stale)    # the file is deleted; its thumbnail stays cached
        self._move([self.plate])
        png = self.images.valid_path(stale)
        self.assertIsNotNone(png, "the moved file has no thumbnail")
        self.assertEqual("#d08040", QtGui.QImage(png).pixelColor(1, 1).name())

    def test_a_picture_not_yet_saved_follows_too(self):
        fresh = os.path.join(self.a, "fresh.exr")
        test_support.write_text(fresh, "fresh")
        self.images.put(fresh, _picture("#80c040"))    # made, and not in the manifest file yet
        self._move([fresh])
        new_path = os.path.join(self.b, "fresh.exr")
        self.assertIsNotNone(self._on_disk(self.images).valid_path(new_path),
                             "a thumbnail the grid had not saved was not re-keyed")

    def test_the_grids_copy_of_an_old_picture_is_dropped(self):
        new_key = texture_library.ThumbnailCache._key(os.path.join(self.b, "plate.exr"))
        stale = ("tex", new_key, self.images.size)    # the key the grid looks up that row's image by
        thumbnails.engine.deposit(stale, _picture("#2040ff"))
        self.addCleanup(thumbnails.engine.discard, stale)
        self._move([self.plate])
        self.assertIsNone(thumbnails.engine.peek(stale), "the grid would paint a stale copy")

    def test_undo_brings_back_the_picture_the_file_has_now(self):
        """Not the stale one cached for its old path, which 1.19.0 showed after a move back."""
        moved = self._move([self.plate])
        new_path = os.path.join(self.b, "plate.exr")
        self.images.put(new_path, _picture("#2040ff"))    # rendered again at the new path
        self.images.save()
        back = file_moves.move(file_moves.back(moved))
        file_moves.rekey_moved_files(self.prefs, back.moved)
        png = self.images.valid_path(self.plate)
        self.assertIsNotNone(png, "the file moved back without a thumbnail")
        self.assertEqual("#2040ff", QtGui.QImage(png).pixelColor(1, 1).name(),
                         "the stale thumbnail of the old path is shown")
        self.assertIsNone(self.images.valid_path(new_path))

    def test_a_hundred_moved_files_render_nothing(self):
        meshes = []
        for at in range(100):
            path = os.path.join(self.a, "m%03d.obj" % at)
            test_support.write_text(path, "v %d 0 0" % at)
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


class ACopyLeavesTheOriginalTest(_Folders):
    """`copy` writes a second file; it replaces a file of that name only when told to."""

    def _copy(self, **kwargs):
        return file_moves.copy([(self.plate, self.moved_to)], **kwargs)

    def test_the_copy_is_complete_and_the_original_stays(self):
        ticks = []
        result = self._copy(tick=ticks.append)
        self.assertEqual([(self.plate, self.moved_to)], result.moved)
        self.assertEqual(("plate", "plate"), (_read(self.plate), _read(self.moved_to)))
        self.assertEqual(len("plate"), sum(ticks), "progress missed bytes")
        self.assertEqual([], self._parts())

    def test_a_name_in_use_is_skipped_and_its_file_is_unchanged(self):
        test_support.write_text(self.moved_to, "other")
        result = self._copy()
        self.assertEqual([(self.plate, self.moved_to)], result.skipped)
        self.assertEqual("other", _read(self.moved_to))
        self.assertEqual([], self._parts())

    def test_replace_writes_over_the_file_of_that_name(self):
        test_support.write_text(self.moved_to, "other")
        result = self._copy(replace=True)
        self.assertEqual([(self.plate, self.moved_to)], result.moved)
        self.assertEqual(("plate", "plate"), (_read(self.plate), _read(self.moved_to)))
        self.assertEqual([], self._parts())

    def test_a_replace_that_fails_keeps_the_file_that_was_there(self):
        test_support.write_text(self.moved_to, "other")
        full = OSError(errno.ENOSPC, "No space left on device")
        with mock.patch.object(os, "fsync", side_effect=full):
            result = self._copy(replace=True)
        self.assertEqual([(self.plate, "No space left on device")], result.failed)
        self.assertEqual("other", _read(self.moved_to))
        self.assertEqual([], self._parts())

    def test_a_file_copied_onto_itself_is_skipped_even_with_replace(self):
        result = file_moves.copy([(self.plate, self.plate)], replace=True)
        self.assertEqual([(self.plate, self.plate)], result.skipped)
        self.assertEqual("plate", _read(self.plate))
        self.assertEqual(["plate.exr"], os.listdir(self.a))

    def test_a_stopped_copy_leaves_nothing_in_the_folder(self):
        result = self._copy(stopped=lambda: True)
        self.assertEqual(([], [], []), tuple(result))
        self.assertEqual([], os.listdir(self.b))


class _FileTabShowingA(unittest.TestCase):
    """The File tab on a location with folders `a` and `b`, showing `a` and its plate.exr."""

    def setUp(self):
        self.panel = test_support.fixture_panel(self)
        self.shown = []
        previous = debug._ui
        debug.set_ui(types.SimpleNamespace(status=self.shown.append,
                                           dialog=self.shown.append))
        self.addCleanup(debug.set_ui, previous)
        self.folders = self.panel.pane.file_folders_model
        self.loc = self.folders.registered_at(self.folders._offset())    # the first location
        self.a, self.b = _child(self.loc, "a"), _child(self.loc, "b")
        self.plate = os.path.join(self.a, "plate.exr")
        self.moved_to = os.path.join(self.b, "plate.exr")
        test_support.write_text(self.plate, "plate")
        os.makedirs(self.b)
        self.panel.section_tabs.setChecked("file")
        QtWidgets.QApplication.processEvents()
        self.section = self.panel.pane.sections["file"]
        _shown(self.folders, self.loc)
        self.assertTrue(test_support.pump_until(
            lambda: self.folders.index_of(self.b).isValid()),
            "premise: the subfolders never arrived")
        self.section._browse(self.a)
        self.assertTrue(test_support.pump_until(lambda: self._tile("plate.exr") is not None),
                        "premise: plate.exr never listed")

    def _tile(self, name):
        proxy = self.panel.pane.file_sorted_model
        for row in range(proxy.rowCount()):
            index = proxy.index(row, 0)
            if index.data() == name:
                return index
        return None

    def _finish(self):
        self.assertTrue(test_support.pump_until(lambda: not file_moves.mover.busy()),
                        "the move or paste never finished")
        QtWidgets.QApplication.processEvents()


class TheFileTabCopiesAndPastesTest(_FileTabShowingA):
    """Copy puts the selected files on the clipboard; Paste copies them into the folder shown."""

    def setUp(self):
        super().setUp()
        clipboard = QtWidgets.QApplication.clipboard()
        self.addCleanup(clipboard.clear)
        clipboard.clear()
        self.asked = []

    def _copy_plate(self):
        tile = self._tile("plate.exr")
        self.section.menu_copy([tile], tile)

    def _show_b(self):
        self.section._browse(self.b)
        self.assertTrue(test_support.pump_until(lambda: self.section._shown_folder() == self.b),
                        "premise: b never shown")

    def _answering(self, choice):
        def ask(text, **kwargs):
            self.asked.append((text, kwargs["buttons"]))
            return choice
        return mock.patch.object(hou, "ui", types.SimpleNamespace(displayMessage=ask),
                                 create=True)

    def test_copy_puts_the_file_on_the_clipboard_as_a_file_and_as_text(self):
        self._copy_plate()
        data = QtWidgets.QApplication.clipboard().mimeData()
        plate = os.path.normpath(self.plate)    # a Windows path is on the clipboard with `/`
        self.assertEqual([plate], [os.path.normpath(url.toLocalFile()) for url in data.urls()])
        self.assertEqual(plate, os.path.normpath(data.text()))

    def test_paste_is_offered_only_with_files_copied_and_a_folder_shown(self):
        self.assertFalse(self.section.menu_paste_enabled([], None), "offered with nothing copied")
        self._copy_plate()
        self.assertTrue(self.section.menu_paste_enabled([], None))
        QtWidgets.QApplication.clipboard().setText("plate.exr")
        self.assertFalse(self.section.menu_paste_enabled([], None), "offered for text")

    def test_paste_copies_the_file_into_the_folder_shown(self):
        self._copy_plate()
        self._show_b()
        self.section.menu_paste([], None)
        self._finish()
        self.assertEqual(("plate", "plate"), (_read(self.plate), _read(self.moved_to)))
        self.assertEqual(messages.PASTE_DONE % ("1 file", "b"), self.shown[-1])
        self.assertEqual([], self.asked)
        self.assertFalse(self.section.can_undo_move([], None), "a paste is offered as Undo Move")

    def test_paste_into_the_files_own_folder_changes_nothing_and_says_so(self):
        self._copy_plate()
        with self._answering(0):
            self.section.menu_paste([], None)
            self._finish()
        self.assertEqual([], self.asked, "asked to overwrite a file with itself")
        self.assertEqual(["plate.exr"], os.listdir(self.a))
        self.assertEqual(messages.PASTE_TAKEN % ("plate.exr", "a"), self.shown[-1])

    def _paste_two_onto_a_name_in_use(self, choice):
        """plate.exr is in `b` already and new.exr is not; both are pasted with `choice` answered."""
        test_support.write_text(self.moved_to, "other")
        new = os.path.join(self.a, "new.exr")
        test_support.write_text(new, "new")
        pane_files.copy_files([self.plate, new])
        self._show_b()
        del self.shown[:]
        with self._answering(choice):
            self.section.menu_paste([], None)
            self._finish()
        self.assertEqual([(messages.PASTE_ASK % ("plate.exr", "b"),
                           messages.BUTTONS_OVERWRITE_OR_SKIP)], self.asked)
        self.assertEqual("plate", _read(self.plate))
        return sorted(os.listdir(self.b)), _read(self.moved_to)

    def test_overwrite_replaces_the_file_of_that_name(self):
        self.assertEqual((["new.exr", "plate.exr"], "plate"),
                         self._paste_two_onto_a_name_in_use(0))
        self.assertEqual(messages.PASTE_DONE % ("2 files", "b"), self.shown[-1])

    def test_skip_pastes_the_others_and_leaves_that_file(self):
        self.assertEqual((["new.exr", "plate.exr"], "other"),
                         self._paste_two_onto_a_name_in_use(1))
        self.assertEqual(messages.PASTE_DONE % ("1 file", "b"), self.shown[-1])

    def test_cancel_pastes_nothing(self):
        self.assertEqual((["plate.exr"], "other"), self._paste_two_onto_a_name_in_use(2))
        self.assertEqual([], self.shown)

    def test_without_a_ui_a_name_in_use_is_skipped(self):
        test_support.write_text(self.moved_to, "other")
        self._copy_plate()
        self._show_b()
        self.assertFalse(hasattr(hou, "ui"), "this host HAS a ui, so the skip is untested")
        self.section.menu_paste([], None)
        self._finish()
        self.assertEqual("other", _read(self.moved_to))

    def test_a_folder_on_the_clipboard_is_named_and_not_pasted(self):
        pane_files.copy_files([self.a, self.plate])
        self._show_b()
        self.section.menu_paste([], None)
        self._finish()
        self.assertEqual(["plate.exr"], os.listdir(self.b))
        self.assertEqual("%s %s" % (messages.PASTE_DONE % ("1 file", "b"),
                                    messages.PASTE_FOLDER % "a"), self.shown[-1])

    def test_a_paste_keeps_the_last_move_undoable(self):
        self.section._last_move = ((self.plate, self.moved_to),)
        self._copy_plate()
        self._show_b()
        self.section.menu_paste([], None)
        self._finish()
        self.assertEqual(((self.plate, self.moved_to),), self.section._last_move)

    def test_the_grid_menu_lists_copy_and_paste_under_new_folder(self):
        labels = [entry.label for entry in self.section.GRID_MENU]
        start = labels.index("New Folder")
        self.assertEqual(["New Folder", "", "Copy", "Paste", "", "Open Scene"],
                         labels[start:start + 6])


class TheFileTabMovesWhatIsDroppedOnAFolderTest(_FileTabShowingA):
    """A release over a folder row moves the selected files there; Undo Move puts them back."""

    def _release_over(self, folder):
        tile = self._tile("plate.exr")
        self.panel.pane.file_selection_model.select(
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
        self.assertTrue(test_support.pump_until(lambda: not file_moves.mover.busy()),
                        "the move never finished")
        QtWidgets.QApplication.processEvents()

    def test_a_release_over_a_folder_moves_the_selection_there(self):
        self._release_over(self.b)
        self.assertEqual("plate", _read(self.moved_to))
        self.assertFalse(os.path.exists(self.plate))
        self.assertTrue(test_support.pump_until(lambda: self._tile("plate.exr") is None),
                        "the moved file is still listed where it was")
        self.assertEqual(messages.MOVE_DONE % ("1 file", "b"), self.shown[-1])

    def test_the_release_moves_the_files_picture(self):
        cache = self.panel.pane.file_files_model._get_image_cache()
        cache.put(self.plate, _picture("#d08040"))
        cache.save()
        self._release_over(self.b)
        cached = texture_library.ThumbnailCache(cache.size).paths()
        self.assertIn(texture_library.ThumbnailCache._key(self.moved_to), cached)
        self.assertNotIn(texture_library.ThumbnailCache._key(self.plate), cached)

    def test_undo_move_restores_the_file(self):
        self.assertFalse(self.section.can_undo_move([], None), "premise: nothing to undo yet")
        self._release_over(self.b)
        self.assertTrue(self.section.can_undo_move([], None), "Undo Move is not offered")
        self.section.menu_undo_move([], None)
        self.assertTrue(test_support.pump_until(lambda: not file_moves.mover.busy()))
        QtWidgets.QApplication.processEvents()
        self.assertEqual("plate", _read(self.plate))
        self.assertFalse(os.path.exists(self.moved_to))
        self.assertEqual(messages.MOVE_BACK % "1 file", self.shown[-1])
        self.assertFalse(self.section.can_undo_move([], None), "Undo Move offered after the undo")

    def test_a_taken_name_is_named_on_the_status_line(self):
        test_support.write_text(self.moved_to, "other")
        self._release_over(self.b)
        self.assertEqual(("plate", "other"), (_read(self.plate), _read(self.moved_to)))
        self.assertEqual(messages.MOVE_TAKEN % ("plate.exr", "b"), self.shown[-1])
        self.assertFalse(self.section.can_undo_move([], None), "nothing moved, yet Undo is offered")

    def test_more_than_three_taken_names_end_in_a_count(self):
        names = ("1.exr", "2.exr", "3.exr", "4.exr", "5.exr")
        skipped = [(os.path.join(self.a, n), os.path.join(self.b, n)) for n in names]
        self.assertEqual(
            [messages.MOVE_TAKEN_MANY % ("1.exr, 2.exr, 3.exr and 2 more", "b")],
            self.section._name_in_use_lines(skipped))

    def test_hovering_a_subfolder_lights_that_row_only(self):
        """Rows are numbered per parent in a tree, so the highlight stores the index, not a row."""
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
        self.assertFalse(delegate.drop_target(target), "hover row -1 left the row highlighted")

    def test_all_takes_no_drop_and_asset_tabs_take_no_file_drop(self):
        view = self.panel.cat_list
        all_row = self.folders.index(0, 0)
        self.assertIsNone(sidebar.folder_at_point(
            self.panel, view.visualRect(all_row).center()))
        self.assertEqual(self.loc, sidebar.folder_at_point(
            self.panel, view.visualRect(self.folders.index_of(self.loc)).center()))
        self.panel.section_tabs.setChecked("material")
        QtWidgets.QApplication.processEvents()
        self.assertIsNone(sidebar.folder_under_cursor(self.panel))
        self.assertFalse(self.panel.pane.sections["material"].takes_file_drops)


if __name__ == "__main__":
    unittest.main()
