"""No reader sees a half-written file; two writers never share a scratch name. ▸r/atomic-writes"""

import gzip
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.helpers import hostos                         # noqa: E402
from amaze.prefs import prefs                            # noqa: E402
from amaze.tests import test_support                     # noqa: E402


class AtomicWriteTest(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_atomic_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "library.json")

    def _leftovers(self):
        return [n for n in os.listdir(self.dir)
                if n != os.path.basename(self.path)]

    def test_the_scratch_name_is_unique_per_writer(self):
        """The scratch name is captured inside the write; it exists only between creation and the rename."""
        seen = []
        real_replace = hostos.replace_file

        def capture(src, dst):
            seen.append(os.path.basename(src))
            return real_replace(src, dst)

        hostos.replace_file = capture
        self.addCleanup(setattr, hostos, "replace_file", real_replace)
        for n in range(8):
            hostos.write_json_atomic(self.path, {"n": n})
        self.assertEqual(
            len(seen), len(set(seen)),
            "the scratch name repeated across writes (%r) - two "
            "concurrent savers would share one buffer" % (seen,))

    def test_concurrent_writers_never_produce_mixed_content(self):
        """Each writer's document is entirely its own; a result holding both marks is silent corruption."""
        errors = []

        def write(mark):
            try:
                for _ in range(40):
                    hostos.write_json_atomic(
                        self.path, {"who": mark, "rows": [mark] * 50})
            except Exception as exc:                     # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=write, args=(m,))
                   for m in ("A", "B")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual([], errors, "a concurrent write raised")

        with open(self.path, encoding="utf-8") as fh:
            final = json.load(fh)
        self.assertIn(final["who"], ("A", "B"))
        self.assertEqual(
            {final["who"]}, set(final["rows"]),
            "the file holds rows from BOTH writers - this is the "
            "parseable corruption the fixed .tmp name produced")

    def test_the_return_value_is_the_fingerprint_of_the_bytes_on_disk(self):
        returned = hostos.write_json_atomic(
            self.path, {"rows": ["a", "é"], "n": 2}, indent=1, sort_keys=True)
        self.assertEqual(hostos.fingerprint_of(self.path), returned,
                         "the returned fingerprint is not of the bytes on disk")

    def test_no_scratch_file_remains_after_a_success(self):
        hostos.write_json_atomic(self.path, {"ok": True})
        self.assertEqual([], self._leftovers(),
                         "a scratch file was left in the library")

    def test_a_failed_write_leaves_no_scratch_and_the_file_intact(self):
        """No leftover a cleanup could call an orphan; the good file stays after a bad write."""
        hostos.write_json_atomic(self.path, {"good": 1})
        with self.assertRaises(TypeError):
            hostos.write_json_atomic(self.path, {"bad": object()})
        self.assertEqual([], self._leftovers(),
                         "a failed write left its scratch file behind")
        with open(self.path, encoding="utf-8") as fh:
            self.assertEqual({"good": 1}, json.load(fh),
                             "a failed write replaced a good file")

    def test_the_scratch_is_created_beside_the_destination(self):
        """`os.rename` cannot cross drives, so the scratch sits beside the destination. ▸r/atomic-writes"""
        seen = []
        real_replace = hostos.replace_file
        hostos.replace_file = lambda src, dst: (
            seen.append(os.path.dirname(os.path.abspath(src))),
            real_replace(src, dst))[1]
        self.addCleanup(setattr, hostos, "replace_file", real_replace)
        hostos.write_json_atomic(self.path, {"x": 1})
        self.assertEqual([os.path.abspath(self.dir)], seen)

    def _windows_rules(self):
        """Replace and remove fail on a read-only file, as Microsoft documents for Windows."""
        real_replace, real_remove = os.replace, os.remove

        def writable(path):
            return bool(os.stat(path).st_mode & stat.S_IWUSR)

        def failing_replace(src, dst):
            if os.path.exists(dst) and not writable(dst):
                raise PermissionError(13, "Access is denied", dst)
            return real_replace(src, dst)

        def failing_remove(path):
            if not writable(path):
                raise PermissionError(13, "Access is denied", path)
            return real_remove(path)

        for name, fake in (("replace", failing_replace),
                           ("remove", failing_remove)):
            patcher = mock.patch.object(os, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)
        sleeper = mock.patch.object(hostos.time, "sleep", lambda _s: None)
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_a_read_only_destination_leaves_no_scratch_behind(self):
        """Windows fails the rename onto a read-only file, and then the delete of a read-only scratch."""
        hostos.write_json_atomic(self.path, {"v": 1})
        os.chmod(self.path, 0o444)
        self._windows_rules()
        with self.assertRaises(PermissionError):
            hostos.write_json_atomic(self.path, {"v": 2})
        self.assertEqual(
            [], self._leftovers(),
            "the refused save left a read-only scratch in the library, "
            "which nothing can remove")

    def test_a_read_only_destination_stays_read_only_after_a_save(self):
        if hostos.is_windows():
            self.skipTest("only POSIX lets a rename replace a read-only file")
        hostos.write_json_atomic(self.path, {"v": 1})
        os.chmod(self.path, 0o444)
        hostos.write_json_atomic(self.path, {"v": 2})
        self.assertEqual(0o444, os.stat(self.path).st_mode & 0o777,
                         "the save made a read-only file writable")
        with open(self.path, encoding="utf-8") as handle:
            self.assertEqual({"v": 2}, json.load(handle))

    def test_a_read_only_scratch_is_still_discarded(self):
        scratch = hostos.unique_scratch(self.path)
        os.chmod(scratch, 0o444)
        self._windows_rules()
        hostos.discard_scratch(scratch)
        self.assertFalse(os.path.exists(scratch),
                         "a read-only scratch still exists after `discard_scratch`")


class EveryScratchWriterIsUniqueTest(unittest.TestCase):
    """Uniqueness is of the name, so each test calls the real writer. ▸r/atomic-writes"""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_scratch_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.seen = []
        self._real_replace = real_replace = hostos.replace_file

        def capture(src, dst):
            self.seen.append(os.path.basename(src))
            return real_replace(src, dst)

        hostos.replace_file = capture
        self.addCleanup(setattr, hostos, "replace_file", real_replace)

    def _assert_unique(self, what):
        self.assertTrue(self.seen, "%s never went through a scratch file "
                                  "at all" % what)
        self.assertEqual(
            len(self.seen), len(set(self.seen)),
            "%s reused a scratch name (%r) - two writers of the same "
            "destination therefore share one buffer" % (what, self.seen))

    def _leftovers(self, directory=None):
        directory = directory or self.dir
        return sorted(n for n in os.listdir(directory) if ".writing" in n
                      or n.endswith(".tmp"))

    def test_prefs_uses_a_unique_scratch(self):
        from amaze.prefs import prefs as prefs_mod
        p = prefs_mod.Prefs()
        p.path = self.dir
        for _ in range(6):
            p.save()
        self._assert_unique("Prefs.save")
        self.assertEqual([], self._leftovers(),
                         "a scratch file was left beside settings.json")

    def _asset_writer(self, asset_id):
        """A handler over `self.dir` as its library, a builder, and the asset's two paths."""
        import hou
        from amaze.core import asset_record, library_files, material
        from amaze.render import nodes

        class _Prefs:
            """Only what the asset paths read: the library folder."""
            dir = self.dir + os.sep

        handler = nodes.NodeHandler.__new__(nodes.NodeHandler)
        handler._preferences = _Prefs()
        builder = hou.node("/obj").createNode("subnet")
        self.addCleanup(builder.destroy)
        group = builder.parmTemplateGroup()
        group.append(hou.FloatParmTemplate("amaze_n", "N", 1))
        builder.setParmTemplateGroup(group)
        mat_path = material.payload_path(_Prefs, asset_id, ".mat", library_files.MATERIALS)
        record_path = asset_record.path_for(_Prefs, asset_id, library_files.MATERIALS)
        return handler, builder, mat_path, record_path

    def test_save_asset_pair_uses_unique_scratches(self):
        """`.mat`/`.json` is the asset itself, with no `.bak-*` backup copy. ▸p/asset-write-unit"""
        from amaze.core import asset_record

        handler, builder, mat_path, record_path = self._asset_writer("ASSET1")

        def write_mat(scratch):
            with open(scratch, "w", encoding="utf-8") as handle:
                handle.write("the node network\n")

        for n in range(4):
            builder.parm("amaze_n").set(n + 1)
            handler.save_asset_pair(mat_path, write_mat, builder, "ASSET1")
        self._assert_unique("save_asset_pair")
        self.assertEqual(8, len([name for name in self.seen if name.startswith("ASSET1")]),
                         "the two files did not each get their own scratch")
        self.assertEqual([], self._leftovers(os.path.dirname(mat_path)),
                         "a scratch file was left in the asset folder, "
                         "where Clean Library will find it and have to "
                         "decide whether it is an orphan")
        values = asset_record.read(record_path)["builder"]["values"]
        self.assertEqual({"val": 4.0}, values.get("amaze_n"))
        with open(mat_path, encoding="utf-8") as handle:
            self.assertEqual("the node network\n", handle.read())

    def test_the_texture_manifest_uses_a_unique_scratch(self):
        """The cache dir derives from a size and a prefix only, so two sessions write through one path."""
        from amaze.core import texture_library

        store = texture_library.ThumbnailCache.__new__(
            texture_library.ThumbnailCache)
        store.cache_dir = self.dir
        store.manifest_path = os.path.join(self.dir, "manifest.json")
        store._unreadable = False
        store.ensure_dir = lambda: True
        for n in range(6):
            store._manifest = {"k%d" % i: {"png": "%d.png" % i}
                               for i in range(n + 1)}
            store._dirty = True
            store.save()
        self._assert_unique("ThumbnailCache.save")
        self.assertEqual([], self._leftovers(),
                         "a scratch file was left in the thumbnail cache, "
                         "where the module's own directory scan will find it")
        with open(store.manifest_path, encoding="utf-8") as handle:
            self.assertEqual(6, len(json.load(handle)),
                             "the manifest is incomplete after the writes")

    def test_the_texture_manifest_keeps_its_on_disk_shape(self):
        """A cache file's format is fixed; reformatting rewrites every manifest on every machine."""
        from amaze.core import texture_library

        store = texture_library.ThumbnailCache.__new__(
            texture_library.ThumbnailCache)
        store.cache_dir = self.dir
        store.manifest_path = os.path.join(self.dir, "manifest.json")
        store._unreadable = False
        store.ensure_dir = lambda: True
        store._manifest = {"a": {"png": "1.png"}, "b": {"png": "2.png"}}
        store._dirty = True
        store.save()
        with open(store.manifest_path, encoding="utf-8") as handle:
            self.assertEqual(json.dumps(store._manifest), handle.read(),
                             "the manifest was reformatted on disk")

    def test_a_download_uses_a_unique_scratch(self):
        """Two fetches of one asset must not share a `.part` name the `finally` removes. ▸r/atomic-writes"""
        from amaze.core import matx_sources
        import io

        dest = os.path.join(self.dir, "texture.png")
        body = b"PNG bytes" * 64

        class _Resp(io.BytesIO):
            """`_request` RETURNS the response; it is not a context-manager factory."""
            headers = {"Content-Length": str(len(body))}

        real_request = matx_sources._request
        matx_sources._request = lambda _url: _Resp(body)
        self.addCleanup(setattr, matx_sources, "_request", real_request)
        scratches = set()   # seen during the download; the file is gone by the end

        def watch(_read, _total):
            scratches.update(n for n in os.listdir(self.dir)
                             if n != "texture.png")

        for _ in range(6):
            matx_sources.download("https://example.invalid/t.png", dest,
                                  on_bytes=watch)
        self.assertEqual(
            6, len(scratches),
            "the download scratch name repeated (%r) - two fetches of one "
            "asset share the buffer, and the cleanup then removes the copy "
            "the other one is about to rename into place" % sorted(scratches))
        self.assertEqual(
            ["texture.png"], sorted(os.listdir(self.dir)),
            "a scratch file was left beside the download")
        with open(dest, "rb") as handle:
            self.assertEqual(body, handle.read())

    def test_the_capture_scratch_is_unique_and_keeps_its_extension(self):
        """A capture scratch keeps its extension: Houdini picks the format from it. ▸r/atomic-writes"""
        from amaze.core import scene_captures

        out = os.path.join(self.dir, "abc123.png")
        seen = set()
        for _ in range(6):
            scratch = scene_captures._capture_scratch(out)
            self.assertTrue(scratch.endswith(".png"),
                            "the scratch name does not end in .png, so "
                            "Houdini would choose a different image format")
            self.assertFalse(
                os.path.exists(scratch),
                "create=False left a file at the name, so Houdini is being "
                "given an existing file after all")
            self.assertEqual(self.dir, os.path.dirname(scratch),
                             "the scratch is not beside its destination")
            seen.add(scratch)
        self.assertEqual(6, len(seen),
                         "the capture scratch name is not unique (%r)"
                         % sorted(seen))

    def test_every_render_scratch_keeps_its_destination_extension(self):
        """Houdini picks the format from the LAST extension; an unknown one writes PIC2. ▸r/image-extension"""
        for name in ("geo_render.png", "frame.exr", "shot.jpg"):
            out = os.path.join(self.dir, name)
            scratch = hostos.render_scratch(out)
            self.assertEqual(
                os.path.splitext(name)[1], os.path.splitext(scratch)[1],
                "the render scratch %r does not end in its destination's "
                "extension, so Houdini writes a format Qt cannot read"
                % os.path.basename(scratch))
            self.assertFalse(os.path.exists(scratch),
                             "a renderer is given a file that exists")

    def test_every_render_scratch_is_named_through_its_helper(self):
        """SOURCE-DERIVED: a capture needs a live viewer, so the call sites are read. ▸p/testing-can-fail"""
        import inspect
        from amaze.actions import files as files_actions
        from amaze.core import scene_captures

        geo = inspect.getsource(files_actions.render_geo_misses)
        capture = inspect.getsource(scene_captures._capture_scratch)
        for where, source in (("the geometry pass", geo),
                              ("the scene capture", capture)):
            self.assertIn(
                "hostos.render_scratch(", source,
                "%s names its own render scratch, so the extension rule "
                "is left to a caller" % where)
        source = inspect.getsource(scene_captures.capture_viewport)
        body = "\n".join(line.split("#")[0]
                         for line in source.splitlines())
        assigns = [line.strip() for line in body.splitlines()
                   if line.strip().startswith("scratch =")]
        self.assertEqual(
            1, len(assigns),
            "capture_viewport no longer has exactly one scratch name - "
            "this test cannot tell which one Houdini is given (%r)" % assigns)
        called = assigns[0].split("=", 1)[1].strip()
        self.assertTrue(
            called.startswith("_capture_scratch("),
            "capture_viewport builds its own scratch name instead of "
            "going through the helper, so the unique-name rule and the "
            "extension rule are both unenforced here (%r)" % called)

    def test_a_scratch_is_not_leaked_when_the_second_one_cannot_be_made(self):
        """When the record scratch cannot be made, the `.mat` scratch made before it is removed."""
        from amaze.tests import test_support
        handler, builder, mat_path, record = self._asset_writer("LEAK")

        def write_mat(scratch):
            with open(scratch, "w", encoding="utf-8") as handle:
                handle.write("net\n")

        with self.assertRaises(OSError), test_support.full_disk_for(record):
            handler.save_asset_pair(mat_path, write_mat, builder, "LEAK")
        self.assertEqual(
            [], sorted(os.listdir(os.path.dirname(mat_path))),
            "the first scratch was left in the asset folder, where Clean "
            "Library has to decide whether it is an orphan")

    def test_preserving_an_unreadable_file_says_nothing_on_screen(self):
        """The helper logs and the caller prints; a line printed inside shows the message twice."""
        import contextlib
        import io

        path = os.path.join(self.dir, "gradients.json")
        for content in ("", '{"gradients": [', '{"gradients": ['):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(content)
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                hostos.preserve_unreadable(path, why="a test")
            self.assertEqual(
                "", printed.getvalue(),
                "preserve_unreadable printed to the user for %r - two "
                "paragraphs about one event" % content)

    def test_save_asset_pair_lets_houdinis_writer_overwrite_the_scratch(self):
        """Houdini's own writer must overwrite the 0-byte file `unique_scratch` pre-creates."""
        import hou
        from amaze.render import nodes

        parent = hou.node("/mat") or hou.node("/shop")
        if parent is None:
            self.skipTest("no /mat context in this build")
        holder = parent.createNode("subnet", "amaze_scratch_probe")
        self.addCleanup(holder.destroy)
        holder.createNode("null", "inside")
        handler = nodes.NodeHandler.__new__(nodes.NodeHandler)
        mat_path = os.path.join(self.dir, "REAL.mat")
        handler.save_asset_pair(
            mat_path,
            lambda scratch: holder.saveItemsToFile(
                holder.children(), scratch, save_hda_fallbacks=False))
        self.assertGreater(
            os.path.getsize(mat_path), 0,
            "Houdini's own writer wrote nothing into a pre-created scratch, "
            "which is the assumption unique_scratch(create=True) rests on")
        self.assertEqual([], self._leftovers(),
                         "the real writer left a scratch behind")

    def test_save_asset_pair_scratches_are_created_beside_their_destinations(self):
        """`os.rename` cannot cross drives, and this pair can live on another volume than the temp dir."""
        directories = []
        real_replace = hostos.replace_file
        hostos.replace_file = lambda src, dst: (
            os.path.basename(src).startswith("A.") and directories.append(
                os.path.dirname(os.path.abspath(src))),
            real_replace(src, dst))[1]
        self.addCleanup(setattr, hostos, "replace_file", real_replace)
        handler, builder, mat_path, _record = self._asset_writer("A")
        handler.save_asset_pair(
            mat_path, lambda scratch: open(scratch, "w").write("net\n"), builder, "A")
        self.assertEqual([os.path.dirname(os.path.abspath(mat_path))] * 2, directories)

    def test_a_failed_mat_write_promotes_neither_file(self):
        """A failed `.mat` write leaves no new builder beside a stale `.mat`. ▸p/asset-write-unit"""
        from amaze.core import asset_record
        import hou

        handler, builder, mat_path, record_path = self._asset_writer("ASSET2")
        os.makedirs(os.path.dirname(mat_path), exist_ok=True)
        old = {"type": "subnet", "interface": "the good old interface", "values": {}}
        asset_record.write_section(record_path, asset_record.BUILDER, old)
        with open(mat_path, "w", encoding="utf-8") as handle:
            handle.write("the good old network\n")
        builder.parm("amaze_n").set(7)

        def write_nothing(_scratch):
            return None             # exactly what a failed save looks like

        with self.assertRaises(hou.OperationFailed):
            handler.save_asset_pair(mat_path, write_nothing, builder, "ASSET2")
        self.assertEqual(
            old, asset_record.read(record_path)["builder"],
            "the builder was replaced although the .mat write "
            "failed - the pair is no longer written as one unit")
        with open(mat_path, encoding="utf-8") as handle:
            self.assertEqual("the good old network\n", handle.read())
        self.assertEqual([], self._leftovers(os.path.dirname(mat_path)),
                         "the failed write left its scratch files behind")

    def test_concurrent_asset_pair_writers_never_mix(self):
        """Mixing is forced with a barrier, so the main assertion can fail. ▸p/testing-can-fail"""
        from amaze.core import asset_record

        hostos.replace_file = self._real_replace
        writers = {mark: self._asset_writer("RACE") for mark in ("A", "B")}
        _handler, _builder, mat_path, record_path = writers["A"]
        for number, mark in enumerate(("A", "B"), 1):
            writers[mark][1].parm("amaze_n").set(number)    # each writer's builder value identifies it
        mixed = []
        raised = []
        scratches = {}
        both_half_written = threading.Barrier(2, timeout=30)

        def write(mark):
            handler, builder = writers[mark][:2]
            body = (mark * 79 + "\n") * 256
            half = len(body) // 2

            def write_mat(scratch):
                scratches[mark] = scratch
                with open(scratch, "w", encoding="utf-8") as handle:
                    handle.write(body[:half])
                    handle.flush()
                    both_half_written.wait()
                    handle.write(body[half:])
                    handle.flush()
                with open(scratch, encoding="utf-8") as handle:
                    marks = sorted(set(handle.read().replace("\n", "")))
                if marks != [mark]:
                    mixed.append("%s's own scratch came back holding %s"
                                 % (mark, marks))

            try:
                handler.save_asset_pair(mat_path, write_mat, builder, "RACE")
            except Exception as exc:                     # noqa: BLE001
                raised.append("%s: %s" % (type(exc).__name__, exc))

        threads = [threading.Thread(target=write, args=(m,))
                   for m in ("A", "B")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        self.assertEqual(
            [], mixed,
            "a writer's scratch held the OTHER writer's bytes - this is the "
            "parseable corruption a shared scratch name produces, and for "
            "the asset itself there is no .bak copy to recover from")
        self.assertEqual(2, len(scratches),
                         "premise: both writers must have reached the .mat")
        self.assertNotEqual(
            scratches["A"], scratches["B"],
            "two overlapping writers got the same scratch path, so "
            "they share one buffer by construction")
        self.assertEqual([], raised, "a concurrent write raised")
        with open(mat_path, encoding="utf-8") as handle:
            marks = set(handle.read().replace("\n", ""))
        self.assertEqual(1, len(marks), "the .mat holds bytes from both writers")
        values = asset_record.read(record_path)["builder"].get("values", {})
        self.assertIn(values.get("amaze_n"), ({"val": 1.0}, {"val": 2.0}),
                      "the .json holds neither writer's builder whole")
        self.assertEqual([], self._leftovers(os.path.dirname(mat_path)),
                         "a scratch file was left after the race")

    def test_a_new_file_gets_exactly_what_a_plain_open_would_have(self):
        """Against `_DEFAULT_FILE_MODE`, not `!= 0o600`, which a 077 umask passes. ▸p/testing-can-fail"""
        if hostos.is_windows():
            self.skipTest("POSIX permission bits are not the model here")
        path = os.path.join(self.dir, "fresh.json")
        hostos.write_json_atomic(path, {"assets": []})
        plain = os.path.join(self.dir, "reference.json")
        with open(plain, "w", encoding="utf-8") as handle:
            handle.write("{}")
        self.assertEqual(
            os.stat(plain).st_mode & 0o777, os.stat(path).st_mode & 0o777,
            "an atomic write does not create the file a plain open() would "
            "have - mkstemp's 0600 reached the destination")

    def test_an_atomic_write_repairs_a_narrowing_the_bug_already_made(self):
        """Matching the destination mode would keep a narrowed file narrowed forever. ▸r/atomic-writes"""
        if hostos.is_windows():
            self.skipTest("POSIX permission bits are not the model here")
        if hostos._DEFAULT_FILE_MODE == 0o600:
            self.skipTest("this machine's umask makes 0600 the correct "
                          "answer, so there is no narrowing to repair")
        path = os.path.join(self.dir, "library.json")
        hostos.write_json_atomic(path, {"assets": []})
        os.chmod(path, 0o600)                   # the state already on disk
        hostos.write_json_atomic(path, {"assets": [{"id": "a"}]})
        self.assertEqual(
            hostos._DEFAULT_FILE_MODE, os.stat(path).st_mode & 0o777,
            "the file stayed owner-only, so the narrowing this morning's "
            "change made is permanent and nobody else can read the library")

    def test_the_repair_is_narrow_enough_to_leave_a_real_choice_alone(self):
        """Only exactly 0600, what mkstemp creates, is repaired; any other narrowing was a choice."""
        if hostos.is_windows():
            self.skipTest("POSIX permission bits are not the model here")
        path = os.path.join(self.dir, "policy.json")
        hostos.write_json_atomic(path, {"a": 1})
        for mode in (0o664, 0o640, 0o604, 0o660, 0o666):    # mkstemp's 0600 must never reach one of these
            os.chmod(path, mode)
            hostos.write_json_atomic(path, {"a": mode})
            self.assertEqual(
                mode, os.stat(path).st_mode & 0o777,
                "an atomic write changed permissions the user chose - the "
                "repair changes modes other than the one it is meant to fix")


class PrefsDoesNotRaiseOnADamagedOrUnwritableFileTest(unittest.TestCase):
    """`settings.json` is read at panel build and written in ordinary use, so neither may raise."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_prefs_hard_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "settings.json")

    def _prefs(self):
        p = prefs.Prefs()
        p.path = self.dir
        return p

    def _write(self, payload):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(payload)

    def test_a_top_level_list_does_not_raise(self):
        """A non-object top level has no `.get()`; raising here fails the panel build, silently."""
        for payload in ('["not", "an", "object"]', '"just a string"'):
            with self.subTest(payload=payload):
                self._write(payload)
                p = self._prefs()
                self.assertFalse(p.load(),
                                 "a wrong-shaped file loaded as usable")
                self.assertTrue(getattr(p, "_load_failed", False),
                                "the write latch was not set, so the next "
                                "save would overwrite the file with defaults")

    def test_a_failed_write_is_recorded_and_does_not_raise(self):
        """A failed prefs write is recorded, not raised; nothing else would report a full disk."""
        p = self._prefs()
        p.load()

        def boom(*args, **kwargs):
            raise OSError(28, "No space left on device")

        original = hostos.write_json_atomic
        hostos.write_json_atomic = boom
        self.addCleanup(setattr, hostos, "write_json_atomic", original)

        with test_support.captured_log() as log:
            p.save()                                  # must not raise
        self.assertTrue(
            log.matching("could not save settings.json", "prefs"),
            "a failed settings write left no log entry at all")


class NoContentWriterTargetsItsDestinationTest(unittest.TestCase):
    """A source scan of the whole package, since asset content has no `.bak-*` copy. ▸r/atomic-writes"""

    SCRATCH_NAMES = {"scratch", "path", "tmp_mat", "tmp", "dest"}

    def _package_root(self):
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_every_saveItemsToFile_writes_to_a_scratch(self):
        import ast
        offenders = []
        root = self._package_root()
        for folder, _dirs, files in os.walk(root):
            if "tests" in os.path.relpath(folder, root).split(os.sep):
                continue
            for name in files:
                if not name.endswith(".py"):
                    continue
                full = os.path.join(folder, name)
                with open(full, encoding="utf-8") as fh:
                    source = fh.read()
                for node in ast.walk(ast.parse(source)):
                    if not (isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Attribute)
                            and node.func.attr == "saveItemsToFile"):
                        continue
                    if len(node.args) < 2:
                        continue
                    dest = node.args[1]
                    if isinstance(dest, ast.Name) and \
                            dest.id in self.SCRATCH_NAMES:
                        continue
                    offenders.append(
                        "%s:%d writes to %s"
                        % (os.path.relpath(full, root), node.lineno,
                           ast.unparse(dest)))
        self.assertEqual(
            [], offenders,
            "a node archive is written straight onto its destination, so a "
            "save that fails partway truncates content that has no backup "
            "copy to restore from:\n  " + "\n  ".join(offenders))


class TwoPanesEditSettingsWithoutClobberTest(unittest.TestCase):
    """`panel.py` builds a Prefs per pane tab, so two writers of `settings.json` is ordinary use."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_prefs_merge_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def _prefs(self):
        p = prefs.Prefs()
        p.path = self.dir
        p.load()
        return p

    def test_every_collected_key_has_a_backing_attribute(self):
        """Every collected key is under `users/<uid>/`, which holds all per-user settings."""
        from amaze.prefs import settings_store
        rules = settings_store.RULES
        self.assertEqual(
            ["users"], [key for key in rules if "/" not in key],
            "a per-user key is merged outside a user block, a second place to store it")
        self.assertEqual("fields", rules.get("users"),
                         "a uid this pane has never seen must be merged "
                         "in full, or a second user is not shown")
        blank = prefs.Prefs()
        for attr in ("_file_folders", "_file_favorites",
                     "_file_location_records", "_users_blocks"):
            self.assertTrue(
                hasattr(blank, attr),
                "the merge result is stored in %s, which a fresh Prefs "
                "does not have" % attr)

    def test_a_scalar_keeps_the_last_saving_panes_value(self):
        """Scalar keys are not merged: the value from the pane that saved last is kept."""
        pane_a = self._prefs()
        pane_a.library_user = "u-one"
        pane_a.save()
        pane_b = self._prefs()

        pane_a.thumbsize = 128
        pane_a.save()
        pane_b.thumbsize = 512
        pane_b.save()

        check = prefs.Prefs()
        check.path = self.dir
        check.load()
        self.assertEqual(512, check.thumbsize,
                         "the last saving pane's value was not kept")


class TheLibraryUserIsTheOneIdentityTest(unittest.TestCase):
    """`library_user` is the user: it keys per-user storage and marks versions. ▸p/identity-is-chosen"""

    def _home(self, prefix="amaze_user_"):
        home = tempfile.mkdtemp(prefix=prefix)
        self.addCleanup(shutil.rmtree, home, True)
        return home

    def _prefs_at(self, home):
        p = prefs.Prefs()
        p.path = home
        p.load()
        return p

    def _write_settings(self, home, document):
        with open(os.path.join(home, "settings.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(document, handle)

    def test_it_persists(self):
        home = self._home()
        p = self._prefs_at(home)
        p.library_user = "  Chosen Name  "
        p.save()
        self.assertEqual("Chosen Name", self._prefs_at(home).library_user)

    def test_no_identity_source_touches_the_author_path(self):
        """No identity reads the account or machine name in any module. ▸p/identity-is-chosen"""
        import io
        import os
        import tokenize
        from amaze.core import users
        folder = os.path.dirname(os.path.abspath(prefs.__file__))
        paths = [os.path.join(folder, name)
                 for name in sorted(os.listdir(folder))
                 if name.endswith(".py")]
        paths.append(os.path.abspath(users.__file__))
        checked = []
        for path in paths:
            name = os.path.basename(path)
            checked.append(name)
            with open(path, encoding="utf-8") as fh:
                raw = fh.read()
            source = "".join(
                token.string for token in tokenize.generate_tokens(
                    io.StringIO(raw).readline)
                if token.type not in (tokenize.COMMENT, tokenize.STRING))
            for banned in ("machine_name", "platform.node", "getpass",
                           'environ["USER"]', "environ.get(\'USER\'",
                           'environ.get("USER"'):
                self.assertNotIn(
                    banned, source,
                    "%s appears in %s - the account or machine name can "
                    "end up as a user's name" % (banned, name))
        self.assertIn("prefs.py", checked)
        self.assertIn("persistence.py", checked)
        self.assertIn("users.py", checked)


class TheUserIsAUidWithANameTest(unittest.TestCase):
    """A user is a UID with a name: a rename changes one name, moves no data. ▸p/identity-is-chosen"""

    def _prefs(self):
        from amaze.tests import test_support
        return test_support.fixture_prefs(self)

    def test_creating_a_user_returns_a_uid_not_the_name(self):
        """The tag is a UID; a name already in the library is not taken twice, in any letters."""
        from amaze.core import users
        p = self._prefs()
        uid = users.create(p, "Plum")
        self.assertTrue(uid)
        self.assertNotEqual("Plum", uid,
                            "the tag is the typed name - a rename would "
                            "then have to move every tagged row")
        self.assertEqual("Plum", users.name_for(p, uid))
        self.assertEqual("", users.create(p, "Plum"), "a second Plum was made")
        self.assertEqual("", users.create(p, " plum "), "a second Plum was made in other letters")
        self.assertEqual(1, len(users.all_users(p)))

    def test_a_rename_cannot_take_another_users_name(self):
        from amaze.core import users
        p = self._prefs()
        plum = users.create(p, "Plum")
        sage = users.create(p, "Sage")
        self.assertFalse(users.rename(p, sage, "plum"), "Sage was renamed to a name Plum has")
        self.assertEqual("Sage", users.name_for(p, sage))
        self.assertTrue(users.rename(p, plum, "PLUM"), "a user could not change the case of its own name")

    def test_preferences_shows_user_name_taken_and_creates_no_user(self):
        import types
        import hou
        from amaze import messages
        from amaze.core import users
        from amaze.dialogs import base_dialog, prefs_dialog
        p = self._prefs()
        users.create(p, "Plum")
        dialog = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dialog.deleteLater)
        shown = []

        class Named:
            canceled = False
            name = "plum"

            def __init__(self, *_a, **_k):
                pass

            def exec(self):
                pass

        ui = types.SimpleNamespace(displayMessage=lambda text, **_k: shown.append(text))
        with mock.patch.object(base_dialog, "NameDialog", Named), \
                mock.patch.object(hou, "ui", ui, create=True):
            dialog._ask_create_library_user()
        self.assertEqual([messages.USER_NAME_TAKEN % "plum"], shown)
        self.assertEqual(1, len(users.all_users(p)), "a second Plum was made")

    def test_renaming_keeps_the_uid(self):
        """THE WHOLE POINT. Nothing tagged is touched by a rename."""
        from amaze.core import users
        p = self._prefs()
        uid = users.create(p, "Plum")
        users.rename(p, uid, "  Vermilion  ")
        self.assertEqual("Vermilion", users.name_for(p, uid),
                         "the new name is not linked to the same UID")
        self.assertIn(uid, users.all_users(p),
                      "the rename created a second user")
        self.assertEqual(1, len(users.all_users(p)))

    def test_the_current_user_is_the_picked_uid(self):
        from amaze.core import users
        p = self._prefs()
        self.assertIsNone(users.current(p), "a library with nobody in it has a user")
        self.assertEqual({}, users.all_users(p), "asking for the user made one")
        uid = users.create(p, "Plum")
        users.adopt(p, uid)
        self.assertEqual(uid, users.current(p))
        self.assertEqual(uid, p.library_user,
                         "the machine-local pointer must hold the UID")

    def test_a_name_left_in_the_pointer_matches_no_user(self):
        """A NAME in the pointer, as the first builds wrote it, matches no user, and none is created."""
        from amaze.core import users
        p = self._prefs()
        p.library_user = "Plum"
        self.assertIsNone(users.current(p))
        self.assertEqual({}, users.all_users(p))

    def test_no_first_run_state_creates_a_user(self):
        """No users, users and no match, a match: the three states, and not one of them makes a user."""
        from amaze.core import users
        p = self._prefs()
        p.library_user = ""
        self.assertEqual(users.MINT, users.first_run_state(p))
        self.assertIsNone(users.current(p))
        self.assertEqual({}, users.all_users(p))

        p = self._prefs()
        users.create(p, "Plum")
        p.library_user = ""
        self.assertEqual(users.ASK, users.first_run_state(p))
        self.assertIsNone(users.current(p),
                          "it created a second identity instead of "
                          "asking which user this is")

        p = self._prefs()
        uid = users.create(p, "Plum")
        p.library_user = uid
        self.assertEqual(users.RESOLVED, users.first_run_state(p))
        self.assertEqual(uid, users.current(p))


class TheUserListRowsTest(unittest.TestCase):
    """The User list holds the library's users, then a create row."""

    def test_the_rows_are_the_users_then_the_create_row(self):
        from PySide6 import QtWidgets
        from amaze.dialogs import user_dialog
        combo = QtWidgets.QComboBox()
        self.addCleanup(combo.deleteLater)
        user_dialog.fill_users(combo, {"uid-a": "Cobalt", "uid-b": "Sienna"})
        self.assertEqual(3, combo.count(), "users plus the create row")
        self.assertEqual(
            user_dialog.CREATE,
            combo.itemData(combo.count() - 1),
            "the create row is not marked with the sentinel, so a "
            "library user named like it could be mistaken for it")


A_USER = "a1b2c3d4e5f60718293a4b5c6d7e8f90"  # the shape `users.create` makes: only a uuid4().hex is read back as an owner
B_USER = "90f8e7d6c5b4a3928170f6e5d4c3b2a1"


class SandboxRaisesOnAWriteOutsideTempTest(unittest.TestCase):
    """The JSON writer raises when a run may write only in temp. ▸p/hand-run-script-is-unguarded"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="amaze_sandbox_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        original = os.environ.get(hostos.SANDBOX_VAR)
        if original is None:
            self.addCleanup(os.environ.pop, hostos.SANDBOX_VAR, None)
        else:
            self.addCleanup(
                os.environ.__setitem__, hostos.SANDBOX_VAR, original)

    def arm(self):
        os.environ[hostos.SANDBOX_VAR] = "1"

    def test_a_write_outside_temp_raises_write_outside_sandbox(self):
        self.arm()
        outside = os.path.join(os.path.expanduser("~"), "amaze_sandbox_probe.json")
        self.assertFalse(os.path.exists(outside), "the fixture path exists")
        with self.assertRaises(hostos.WriteOutsideSandbox):
            hostos.write_json_atomic(outside, {"a": 1})
        self.assertFalse(
            os.path.exists(outside),
            "the refusal did not happen before the write - the file is "
            "on disk, which is the whole thing this prevents")

    def test_a_write_inside_temp_still_succeeds(self):
        self.arm()
        inside = os.path.join(self.tmp, "fine.json")
        hostos.write_json_atomic(inside, {"a": 1})
        with open(inside, encoding="utf-8") as handle:
            self.assertEqual({"a": 1}, json.load(handle))

    def test_unarmed_it_does_nothing_at_all(self):
        """Nothing in the product sets the variable; a sandbox left on would block real saves."""
        os.environ.pop(hostos.SANDBOX_VAR, None)
        self.assertFalse(hostos.sandboxed())
        outside = os.path.join(self.tmp, "..", os.path.basename(self.tmp),
                               "unarmed.json")
        hostos.write_json_atomic(outside, {"a": 1})
        self.assertTrue(os.path.exists(outside))
        hostos.check_sandbox("/anywhere/at/all.json")


class SandboxRaisesInEveryWritePrimitiveTest(unittest.TestCase):
    """Every shared write primitive refuses a path outside the temp dir, not only the JSON one."""

    def setUp(self):
        base = tempfile.mkdtemp(prefix="amaze_sandbox_prim_")
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        self.inside = os.path.join(base, "inside")
        self.outside = os.path.join(base, "outside")
        os.makedirs(self.inside)
        os.makedirs(self.outside)
        self.addCleanup(setattr, tempfile, "tempdir", tempfile.tempdir)
        tempfile.tempdir = self.inside    # `outside` is outside the temp dir for this test only
        original = os.environ.get(hostos.SANDBOX_VAR)
        if original is None:
            self.addCleanup(os.environ.pop, hostos.SANDBOX_VAR, None)
        else:
            self.addCleanup(
                os.environ.__setitem__, hostos.SANDBOX_VAR, original)
        os.environ[hostos.SANDBOX_VAR] = "1"

    def _assert_raises_outside_sandbox(self, call, *args):
        before = sorted(os.listdir(self.outside))
        with self.assertRaises(hostos.WriteOutsideSandbox):
            call(*args)
        self.assertEqual(before, sorted(os.listdir(self.outside)),
                         "%s wrote outside the temp dir before refusing"
                         % call.__name__)

    def _write_outside(self, name, text):
        path = os.path.join(self.outside, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def _inside_file(self):
        path = os.path.join(self.inside, "scratch.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{}")
        return path

    def test_a_scratch_beside_an_outside_path_raises(self):
        target = os.path.join(self.outside, "a.json")
        self._assert_raises_outside_sandbox(hostos.unique_scratch, target)

        def through_the_context(path):
            with hostos.scratch_beside(path):
                pass
        self._assert_raises_outside_sandbox(through_the_context, target)

    def test_a_promote_or_replace_onto_an_outside_path_raises(self):
        target = os.path.join(self.outside, "a.json")
        self._assert_raises_outside_sandbox(hostos.replace_with_scratch, self._inside_file(), target)
        self._assert_raises_outside_sandbox(hostos.replace_file, self._inside_file(), target)

    def test_the_unreadable_copy_outside_raises(self):
        broken = self._write_outside("bad.json", "{ truncated")
        self._assert_raises_outside_sandbox(hostos.preserve_unreadable, broken)

    def test_a_trash_move_outside_raises(self):
        from amaze.core import guard
        library = os.path.join(self.outside, "library")
        os.makedirs(os.path.join(library, "materials"))
        leftover = os.path.join(library, "materials", "LEFTOVER.mat")
        with open(leftover, "w", encoding="utf-8") as handle:
            handle.write("x")
        change = guard.Guard(library).change("")
        change.trash("materials/LEFTOVER.mat")
        with self.assertRaises(hostos.WriteOutsideSandbox):
            change.commit()
        self.assertTrue(os.path.exists(leftover), "the refused move still moved the file")

    def test_a_cache_folder_made_outside_raises(self):
        self.addCleanup(hostos.set_cache_override, hostos._cache_override)
        hostos.set_cache_override(os.path.join(self.outside, "cache"))
        self._assert_raises_outside_sandbox(hostos.cache_root)


class SandboxKeepsThePerUserFoldersInTempTest(unittest.TestCase):
    """Sandboxed, the settings, cache and log folders are in temp, so a suite save's history is too."""

    def setUp(self):
        original = os.environ.get(hostos.SANDBOX_VAR)
        if original is None:
            self.addCleanup(os.environ.pop, hostos.SANDBOX_VAR, None)
        else:
            self.addCleanup(
                os.environ.__setitem__, hostos.SANDBOX_VAR, original)

    def _assert_in_temp(self):
        temp = os.path.realpath(tempfile.gettempdir()) + os.sep
        for label, path in (("settings", hostos.config_root()),
                            ("cache", hostos.cache_root()),
                            ("log", hostos.log_root())):
            self.assertTrue(
                os.path.realpath(path).startswith(temp),
                "the %s folder is %s, outside the temp dir %s"
                % (label, path, temp))

    def test_armed_every_per_user_folder_is_inside_temp(self):
        os.environ[hostos.SANDBOX_VAR] = "1"
        self._assert_in_temp()
        self.assertNotEqual(
            os.path.realpath(hostos.real_config_root()),
            os.path.realpath(hostos.config_root()),
            "the settings folder is still the user's own")

    def test_the_redirect_is_kept_after_a_reload_of_hostos(self):
        import importlib
        os.environ[hostos.SANDBOX_VAR] = "1"
        before = hostos.config_root()
        importlib.reload(hostos)
        self.assertEqual(before, hostos.config_root(),
                         "a reload moved the settings folder")
        self._assert_in_temp()

    def test_unarmed_the_folders_are_the_users_own(self):
        """Nothing in the product sets it, so a real session must never get the temp folder."""
        held = os.environ.get(hostos.SANDBOX_HOME_VAR)
        if held is None:
            self.addCleanup(os.environ.pop, hostos.SANDBOX_HOME_VAR, None)
        else:
            self.addCleanup(
                os.environ.__setitem__, hostos.SANDBOX_HOME_VAR, held)
        os.environ.pop(hostos.SANDBOX_VAR, None)
        os.environ[hostos.SANDBOX_HOME_VAR] = tempfile.gettempdir()
        self.assertEqual("", hostos.sandbox_home(),
                         "a run without the sandbox returned the temp folder")


class OnePathHasOneSpelling(unittest.TestCase):
    """Both encoders spell a path one way, `~` over a `$AMAZE/..` path; both decoders read both."""

    def _cases(self):
        from amaze.helpers import hostos
        amaze = os.environ.get("AMAZE", "")
        home = os.path.expanduser("~")
        cases = [os.path.join(home, "textures", "wood"),
                 home,
                 "/Volumes/Share/textures"]
        if amaze:
            # The case that differs: shares a parent with the install, not under it.
            cases.append(os.path.join(
                os.path.dirname(amaze), "Sibling", "textures"))
            cases.append(os.path.join(amaze, "scripts"))
        return cases, hostos

    def test_both_encoders_spell_a_path_the_same_way(self):
        from amaze.prefs import persistence
        cases, hostos = self._cases()
        disagree = [(p, persistence._encode_path(p),
                     hostos.storage_path_key(p))
                    for p in cases
                    if persistence._encode_path(p)
                    != hostos.storage_path_key(p)]
        self.assertEqual(
            [], disagree,
            "one folder is spelled two ways in two files: %s" % disagree)

    def test_the_old_parent_relative_spelling_is_still_read(self):
        """Nothing migrates, so the `$AMAZE/..` form this stops writing must keep resolving."""
        from amaze.prefs import persistence
        cases, hostos = self._cases()
        amaze = os.environ.get("AMAZE", "")
        if not amaze:
            self.skipTest("$AMAZE is not set in this environment")
        target = os.path.join(os.path.dirname(amaze), "Sibling", "textures")
        walked = "$AMAZE/../Sibling/textures"
        self.assertEqual(
            os.path.normpath(target),
            os.path.normpath(persistence._decode_path(walked)),
            "an existing settings.json entry stopped resolving")

    def test_a_trailing_separator_survives_the_round_trip(self):
        """`directory` keeps its separator; the home part comes from `posix_path`, not string joining."""
        from amaze.prefs import persistence
        for path in (test_support.posix_path(os.path.expanduser("~"))
                     + "/Cloud/lib/",
                     "/Volumes/Share/lib/"):
            self.assertEqual(
                path, persistence._decode_path(
                    persistence._encode_path(path)),
                "the library pointer lost its trailing separator")


class ImportingTheHarnessArmsTheSandboxTest(unittest.TestCase):
    """A test run without the runner is sandboxed by `test_support`. ▸p/hand-run-script-is-unguarded"""

    CHILD = ("from amaze.core import library_db\n"
             "from amaze.tests import test_support\n"
             "from amaze.helpers import hostos\n"
             "print('ARMED=%s' % hostos.sandboxed())\n"
             "print('SETTINGS=%s' % hostos.config_root())\n")

    def _bare_run(self):
        """{key: value} the child printed, run with none of the runner's sandbox environment."""
        log = tempfile.mkdtemp(prefix="amaze_bare_run_log_")
        self.addCleanup(shutil.rmtree, log, True)
        env = dict(os.environ, AMAZE_LOG_DIR=log, PYTHONPATH=os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        for name in (hostos.SANDBOX_VAR, hostos.SANDBOX_HOME_VAR):
            env.pop(name, None)
        result = subprocess.run([test_support.plain_python(), "-c", self.CHILD],
                                capture_output=True, text=True, env=env,
                                timeout=300)
        self.assertEqual(0, result.returncode,
                         "the bare run failed: %s" % result.stderr[-800:])
        return dict(line.split("=", 1) for line in result.stdout.splitlines()
                    if line.startswith(("ARMED=", "SETTINGS=")))

    def test_a_module_run_without_the_runner_is_armed(self):
        printed = self._bare_run()
        self.assertEqual(
            "True", printed.get("ARMED"),
            "a test module started without start_test.sh has no sandbox, so "
            "it can write the user's real settings folder")
        self.assertNotEqual(
            os.path.realpath(hostos.real_config_root()),
            os.path.realpath(printed.get("SETTINGS", "")),
            "the bare run's settings folder is the user's own")


class TheSandboxStaysArmedForTheSuiteTest(unittest.TestCase):
    """`AMAZE_SANDBOX` stays set for the whole process; named to sort after the sandbox classes."""

    def test_the_armed_state_is_still_set_after_the_sandbox_tests(self):
        self.assertTrue(
            hostos.sandboxed(),
            "a sandbox test turned the sandbox off and never back on "
            "- every test after this module can now write live data")


class TextFilesAreTheSameBytesOnEveryOS(unittest.TestCase):
    """Windows text mode uses the locale and `\\r\\n`; open() is read from source. ▸r/platform-files"""

    def _text_opens(self) -> list:
        """(file:line, mode, keywords) for every built-in open() not in binary mode, tests excluded."""
        import ast
        package = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        found = []
        for root, dirs, files in os.walk(package):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", "tests")]
            for filename in files:
                if not filename.endswith(".py"):
                    continue
                path = os.path.join(root, filename)
                with open(path, encoding="utf-8") as handle:
                    tree = ast.parse(handle.read())
                for node in ast.walk(tree):
                    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                            and node.func.id == "open"):
                        continue
                    keywords = {k.arg for k in node.keywords}
                    mode = node.args[1] if len(node.args) > 1 else next(
                        (k.value for k in node.keywords if k.arg == "mode"), None)
                    mode = mode.value if isinstance(mode, ast.Constant) else "r"
                    if "b" not in mode:
                        where = "%s:%d" % (os.path.relpath(path, package).replace(os.sep, "/"),
                                           node.lineno)
                        found.append((where, mode, keywords))
        return found

    def test_the_scan_still_finds_the_package_opens(self):
        self.assertGreaterEqual(len(self._text_opens()), 30,    # ▸p/vacuous-register
                                "the scan stopped matching, so an empty result proves nothing")

    def test_every_text_open_names_its_encoding(self):
        bare = [where for where, _mode, keywords in self._text_opens()
                if "encoding" not in keywords]
        self.assertEqual([], bare, "these read or write in the locale's encoding, "
                                   "which is cp1252 on a Windows Python: %s" % bare)

    def test_every_text_write_names_its_newline(self):
        bare = [where for where, mode, keywords in self._text_opens()
                if any(c in mode for c in "wax+") and "newline" not in keywords]
        self.assertEqual([], bare, "these write \\r\\n on Windows and \\n elsewhere: %s" % bare)


if __name__ == "__main__":
    unittest.main(verbosity=2)
