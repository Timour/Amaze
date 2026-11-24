"""The file-move requirements, docs/requirements/file-moves.md, one test each."""

import errno
import os
import shutil
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from amaze import messages  # noqa: E402
from amaze.core import captures, file_moves, library_db, locations, users  # noqa: E402
from amaze.helpers import hostos  # noqa: E402
from amaze.tests import test_support  # noqa: E402


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _wait_for_the_mover():
    deadline = time.monotonic() + 10
    while file_moves.mover.busy() and time.monotonic() < deadline:
        _app.processEvents()
        time.sleep(0.01)


class _Folders(unittest.TestCase):
    """Folders `a` and `b` under one scratch root, `a` holding plate.exr."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="amaze_move_")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.a, self.b = os.path.join(self.root, "a"), os.path.join(self.root, "b")
        self.plate, self.moved_to = os.path.join(self.a, "plate.exr"), os.path.join(self.b, "plate.exr")
        test_support.write_text(self.plate, "plate")
        os.makedirs(self.b)

    def leftovers(self):
        return sorted(name for name in os.listdir(self.b) if name != "plate.exr")


class AFileIsNeverLostTest(_Folders):

    def test_fm01_a_file_at_the_destination_is_only_replaced_when_the_user_chose_to(self):
        test_support.write_text(self.moved_to, "other")
        pairs = [(self.plate, self.moved_to)]
        self.assertEqual(pairs, file_moves.move(pairs).skipped)
        self.assertEqual(pairs, file_moves.copy(pairs).skipped)
        self.assertFalse(file_moves.place(self.plate, self.moved_to), "a rename wrote over a file")
        self.assertEqual(("plate", "other"), (_read(self.plate), _read(self.moved_to)))
        self.assertEqual(pairs, file_moves.copy(pairs, replace=True).moved)
        self.assertEqual("plate", _read(self.moved_to))
        self.assertEqual([], file_moves.copy([(self.plate, self.plate)], replace=True).moved)
        self.assertEqual("plate", _read(self.plate))

    def test_fm02_a_move_or_copy_cut_off_at_any_moment_leaves_every_file_whole(self):
        test_support.write_text(self.plate, "123456789abc")    # three blocks of 4
        half = []    # the destination name holding a file mid-copy: what a crash would leave

        def after(blocks, then):
            """A callback that does `then` once `blocks` blocks have gone by."""
            seen = [0]

            def call(*_args):
                seen[0] += 1
                half.append(os.path.lexists(self.moved_to))
                return then() if seen[0] > blocks else False
            return call

        def full():
            raise OSError(errno.ENOSPC, "No space left on device")
        cuts = []
        for blocks in (0, 1, 2, 3):    # a stop before the first block, between blocks, before the rename
            cuts += [lambda b=blocks: file_moves.copy_across(self.plate, self.moved_to,
                                                             stopped=after(b, lambda: True)),
                     lambda b=blocks: file_moves.write_copy(self.plate, self.moved_to,
                                                            stopped=after(b, lambda: True))]
        for blocks in (0, 1, 2):    # the disk full at the first, second or third block
            cuts.append(lambda b=blocks: file_moves.copy_across(self.plate, self.moved_to,
                                                                tick=after(b, full)))
        with mock.patch.object(file_moves, "CHUNK", 4):
            for cut in cuts:
                with self.assertRaises((file_moves.Stopped, OSError)):
                    cut()
                self.assertEqual("123456789abc", _read(self.plate))
                self.assertEqual([], os.listdir(self.b), "a part or half file was left")
        self.assertNotIn(True, half, "a crash mid-copy would leave a half file under the real name")

    def test_fm03_a_move_across_drives_keeps_both_files_when_the_original_cannot_go(self):
        with mock.patch.object(hostos, "remove_file",
                               side_effect=PermissionError(errno.EACCES, "in use")):
            with self.assertRaises(OSError) as raised:
                file_moves.copy_across(self.plate, self.moved_to)
        self.assertIn(messages.MOVE_KEPT_BOTH.split("%s")[0], str(raised.exception))
        self.assertEqual(("plate", "plate"), (_read(self.plate), _read(self.moved_to)))
        self.assertEqual([], self.leftovers())


class SceneWorkIsNeverLostTest(_Folders):

    def test_fm10_the_scene_open_in_houdini_is_never_moved(self):
        other = os.path.join(self.a, "other.exr")
        test_support.write_text(other, "other")
        pairs, kept = file_moves.targets([self.plate, other], self.b, scene=self.plate)
        self.assertEqual(([(other, os.path.join(self.b, "other.exr"))], [self.plate]), (pairs, kept))

    def test_fm11_a_file_another_program_holds_is_tried_again_then_left_and_reported(self):
        real, refusals = hostos.rename_exclusive, [2]

        def held(source, dest):
            if refusals[0]:
                refusals[0] -= 1
                raise PermissionError(errno.EACCES, "in use")
            return real(source, dest)
        with mock.patch.object(hostos, "is_windows", return_value=True), \
                mock.patch.object(hostos, "rename_exclusive", held):
            self.assertEqual([(self.plate, self.moved_to)], file_moves.move([(self.plate, self.moved_to)]).moved)
            refusals[0] = 100    # held for good
            failed = file_moves.move([(self.moved_to, self.plate)]).failed
        self.assertEqual([self.moved_to], [source for source, _why in failed])
        self.assertEqual("plate", _read(self.moved_to))


class WhatAMoveDoesTest(_Folders):

    def test_fm20_a_moved_file_keeps_its_data_for_every_user_and_a_copy_gets_none(self):
        test_support.reset_database_singletons()
        self.addCleanup(test_support.reset_database_singletons)
        prefs = types.SimpleNamespace(dir=os.path.join(self.root, "library") + os.sep,
                                      library_user=test_support.FIXTURE_USER)
        os.makedirs(prefs.dir)
        test_support.with_fixture_user(prefs.dir)
        other = users.create(prefs, "Other")
        self.assertTrue(locations.register(prefs, self.root))
        old, new = captures.file_key(prefs, self.plate), captures.file_key(prefs, self.moved_to)
        held = library_db.document(prefs, locations.FILES)
        held.put(locations.COMMENTS, old, {"items": [{"t": "text", "text": "kept"}]})
        held.put(locations.ICONS, old, {"name": "activity"})
        library_db.save(prefs, locations.FILES)
        for user in (other, test_support.FIXTURE_USER):
            prefs.library_user = user
            self.assertTrue(locations.set_favourite(prefs, self.plate, True))
        test_support.write_text(captures.file_path(prefs, old), "picture")

        def data(key):
            return (bool(held.get(locations.COMMENTS, key)), bool(held.get(locations.ICONS, key)),
                    captures.exists(captures.file_path(prefs, key)),
                    sorted(user for user, own in held.everyones(locations.FAVORITES).items() if key in own))
        file_moves.mover.start([(self.plate, self.moved_to)], prefs, lambda *_: None, lambda _r: None)
        _wait_for_the_mover()
        self.assertEqual((True, True, True, sorted([other, test_support.FIXTURE_USER])), data(new))
        copied = os.path.join(self.a, "plate.exr")
        file_moves.mover.start([(self.moved_to, copied)], prefs, lambda *_: None, lambda _r: None,
                               copying=True)
        _wait_for_the_mover()
        self.assertEqual("plate", _read(copied))
        self.assertEqual((False, False, False, []), data(captures.file_key(prefs, copied)))

    def test_fm21_a_move_tells_what_moved_what_was_skipped_and_what_failed_and_why(self):
        taken, gone = os.path.join(self.a, "taken.exr"), os.path.join(self.a, "gone.exr")
        test_support.write_text(taken, "mine")
        test_support.write_text(os.path.join(self.b, "taken.exr"), "theirs")
        pairs, _kept = file_moves.targets([self.plate, taken, gone], self.b)
        result = file_moves.move(pairs)
        self.assertEqual(([(self.plate, self.moved_to)], [(taken, os.path.join(self.b, "taken.exr"))]),
                         (result.moved, result.skipped))
        self.assertEqual([gone], [source for source, _why in result.failed])
        self.assertTrue(result.failed[0][1], "a failure without its reason")

    def test_fm22_undo_moves_the_last_moves_files_back(self):
        moved = file_moves.move([(self.plate, self.moved_to)]).moved
        self.assertEqual([(self.moved_to, self.plate)], file_moves.move(file_moves.back(moved)).moved)
        self.assertEqual("plate", _read(self.plate))

    def test_fm23_a_second_move_is_refused_while_one_runs(self):
        release = threading.Event()

        def held_copy(pairs, *args, **kwargs):
            release.wait(5)
            return file_moves.Result([], [], [])
        prefs = types.SimpleNamespace(dir="", library_user="")
        with mock.patch.object(file_moves, "copy", held_copy):
            self.assertTrue(file_moves.mover.start([(self.plate, self.moved_to)], prefs,
                                                   lambda *_: None, lambda _r: None, copying=True))
            self.assertFalse(file_moves.mover.start([(self.plate, self.moved_to)], prefs,
                                                    lambda *_: None, lambda _r: None))
            release.set()
            _wait_for_the_mover()
        self.assertFalse(file_moves.mover.busy())

    def test_fm24_a_file_already_in_the_destination_folder_stays_where_it_is(self):
        self.assertEqual(([], []), file_moves.targets([self.plate], self.a))

    def test_fm25_a_moved_or_copied_file_keeps_its_dates(self):
        when = time.time() - 86400 * 30
        os.utime(self.plate, (when, when))
        for keep in (file_moves.write_copy, file_moves.copy_across):
            keep(self.plate, self.moved_to)
            self.assertAlmostEqual(when, os.path.getmtime(self.moved_to), delta=1, msg=keep.__name__)
            os.remove(self.moved_to)


if __name__ == "__main__":
    unittest.main()
