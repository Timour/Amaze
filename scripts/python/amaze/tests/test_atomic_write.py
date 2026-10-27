"""The write path: no reader may ever see a half-written database - the property pinned is that two writers cannot share a scratch NAME, because the corruption that parses is the one nothing downstream detects. ▸r/atomic-writes ▸p/asset-write-unit ▸archive/test_atomic_write.py"""

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
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.helpers import hostos                         # noqa: E402
from amaze.prefs import prefs                            # noqa: E402
from amaze.tests import test_support                     # noqa: E402,F401


class AtomicWriteTest(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_atomic_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "library.json")

    def _leftovers(self):
        return [n for n in os.listdir(self.dir)
                if n != os.path.basename(self.path)]

    def test_the_scratch_name_is_unique_per_writer(self):
        """THE regression, captured from inside the write - the scratch exists only between creation and the rename."""
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
        """The measured failure in-process: each writer's document is entirely its own, so any result holding both marks is the silent corruption."""
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

    def test_the_answer_is_the_fingerprint_of_the_bytes_on_disk(self):
        answer = hostos.write_json_atomic(
            self.path, {"rows": ["a", "é"], "n": 2}, indent=1, sort_keys=True)
        self.assertEqual(hostos.fingerprint_of(self.path), answer,
                         "the writer names bytes other than the ones it wrote")

    def test_no_scratch_file_survives_a_success(self):
        hostos.write_json_atomic(self.path, {"ok": True})
        self.assertEqual([], self._leftovers(),
                         "a scratch file was left in the library")

    def test_a_failed_write_leaves_no_scratch_and_the_file_intact(self):
        """No leftover for a sweep to call an orphan, and the good file outlives the bad write."""
        hostos.write_json_atomic(self.path, {"good": 1})
        with self.assertRaises(TypeError):
            hostos.write_json_atomic(self.path, {"bad": object()})
        self.assertEqual([], self._leftovers(),
                         "a failed write left its scratch file behind")
        with open(self.path, encoding="utf-8") as fh:
            self.assertEqual({"good": 1}, json.load(fh),
                             "a failed write replaced a good file")

    def test_the_scratch_lives_beside_the_destination(self):
        """`os.rename` cannot cross drives, so a scratch in the system temp dir fails every save on a library held on another volume. ▸r/atomic-writes"""
        seen = []
        real_replace = hostos.replace_file
        hostos.replace_file = lambda src, dst: (
            seen.append(os.path.dirname(os.path.abspath(src))),
            real_replace(src, dst))[1]
        self.addCleanup(setattr, hostos, "replace_file", real_replace)
        hostos.write_json_atomic(self.path, {"x": 1})
        self.assertEqual([os.path.abspath(self.dir)], seen)

    def _windows_rules(self):
        """Replace and remove refuse a read-only file, as Microsoft documents for Windows."""
        real_replace, real_remove = os.replace, os.remove

        def writable(path):
            return bool(os.stat(path).st_mode & stat.S_IWUSR)

        def refusing_replace(src, dst):
            if os.path.exists(dst) and not writable(dst):
                raise PermissionError(13, "Access is denied", dst)
            return real_replace(src, dst)

        def refusing_remove(path):
            if not writable(path):
                raise PermissionError(13, "Access is denied", path)
            return real_remove(path)

        for name, fake in (("replace", refusing_replace),
                           ("remove", refusing_remove)):
            patcher = mock.patch.object(os, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)
        sleeper = mock.patch.object(hostos.time, "sleep", lambda _s: None)
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_a_read_only_destination_leaves_no_scratch_behind(self):
        """Windows refuses the swap onto a read-only file, and then the delete of a read-only scratch."""
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
                         "a read-only scratch outlived its discard")


class EveryScratchWriterIsUniqueTest(unittest.TestCase):
    """Uniqueness is a property of the NAME, so each test drives the REAL writer rather than the shared helper - a call site keeping its own fixed name is the bug. ▸r/atomic-writes"""

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

    def test_library_policy_uses_a_unique_scratch(self):
        from amaze.core import library_policy
        for allowed in (True, False, True, False, True, False):
            self.assertTrue(
                library_policy.set_allow_overwrite(self.dir, allowed),
                "the policy write failed, so this proves nothing")
        self._assert_unique("library_policy._write")
        self.assertEqual([], self._leftovers(),
                         "a scratch file was left beside policy.json")
        # And it still round-trips - a fix that broke the setting is worse than the defect.
        self.assertFalse(library_policy.allow_overwrite(self.dir),
                         "the last written value was not read back")

    def test_tile_icons_uses_a_unique_scratch(self):
        from amaze.core import keyed_store, tile_icons

        class _Prefs:
            """Only what `tile_icons` reads - a real Prefs under hython resolves `$AMAZE` to the live install."""

            def __init__(self, directory):
                self.dir = directory
                self.img_dir = "img/"
                self.img_ext = ".png"

        prefs = _Prefs(self.dir + os.sep)
        tile_icons.forget_overrides()
        self.addCleanup(tile_icons.forget_overrides)
        # Through the ENGINE's resolver - one place composes the path for every keyed side table.
        path = keyed_store.open_store(tile_icons.SPEC, prefs).path
        for n in range(6):
            self.assertTrue(
                tile_icons.set_override(
                    prefs, "ASSET%d" % n, {"name": "box", "bg": "#ef8878"}),
                "the icon write failed, so this proves nothing")
        self._assert_unique("keyed_store.Store._commit")
        self.assertEqual([], self._leftovers(os.path.dirname(path)),
                         "a scratch file was left beside icons.json")
        with open(path, encoding="utf-8") as handle:
            self.assertEqual(6, len(json.load(handle)["icons"]),
                             "the icon table did not survive the writes")

    def test_save_asset_pair_uses_unique_scratches(self):
        """THE ONE THAT MATTERS MOST: `.mat`/`.interface` IS the asset and has no `.bak-*` tier behind it. ▸p/asset-write-unit"""
        from amaze.render import nodes

        handler = nodes.NodeHandler.__new__(nodes.NodeHandler)
        interface_path = os.path.join(self.dir, "ASSET1.interface")
        mat_path = os.path.join(self.dir, "ASSET1.mat")

        def write_mat(scratch):
            with open(scratch, "w", encoding="utf-8") as handle:
                handle.write("the node network\n")

        for n in range(4):
            handler.save_asset_pair(
                interface_path, mat_path, "promoted parms %d\n" % n,
                write_mat)
        self._assert_unique("save_asset_pair")
        self.assertEqual(8, len(self.seen),
                         "the two files did not each get their own scratch")
        self.assertEqual([], self._leftovers(),
                         "a scratch file was left in the asset folder, "
                         "where Clean Library will find it and have to "
                         "decide whether it is an orphan")
        with open(interface_path, encoding="utf-8") as handle:
            self.assertEqual("promoted parms 3\n", handle.read())
        with open(mat_path, encoding="utf-8") as handle:
            self.assertEqual("the node network\n", handle.read())

    def test_the_texture_manifest_uses_a_unique_scratch(self):
        """The LIVE case: the cache directory is derived from a size and a prefix, nothing per-process, so two sessions write it through one path."""
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
                             "the manifest did not survive the writes")

    def test_the_texture_manifest_keeps_its_on_disk_shape(self):
        """A cache file's bytes are a contract too - reformatting rewrites every manifest on every machine for no reason."""
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
        """Two fetches of one asset shared the `.part` name, and the `finally` removed whichever copy was still there. ▸r/atomic-writes"""
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
        scratches = set()   # caught mid-flight; the name is gone by the end

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
            "the other one is about to promote" % sorted(scratches))
        self.assertEqual(
            ["texture.png"], sorted(os.listdir(self.dir)),
            "a scratch file was left beside the download")
        with open(dest, "rb") as handle:
            self.assertEqual(body, handle.read())

    def test_the_capture_scratch_is_unique_and_keeps_its_extension(self):
        """Two sessions capturing one scene shared the `.capturing` name, and the extension must survive because Houdini picks the image FORMAT from it. ▸r/atomic-writes"""
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
                "handed an existing file after all")
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
                             "a renderer is handed a file that exists")

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
                "is back in a caller's hands" % where)
        source = inspect.getsource(scene_captures.capture_viewport)
        body = "\n".join(line.split("#")[0]
                         for line in source.splitlines())
        assigns = [line.strip() for line in body.splitlines()
                   if line.strip().startswith("scratch =")]
        self.assertEqual(
            1, len(assigns),
            "capture_viewport no longer has exactly one scratch name - "
            "this test cannot say which one Houdini is handed (%r)" % assigns)
        called = assigns[0].split("=", 1)[1].strip()
        self.assertTrue(
            called.startswith("_capture_scratch("),
            "capture_viewport builds its own scratch name instead of "
            "going through the helper, so the unique-name rule and the "
            "extension rule are both back in play here (%r)" % called)

    def test_a_scratch_is_not_leaked_when_the_second_one_cannot_be_made(self):
        """Both scratches are created INSIDE the try, so a failure of the SECOND cannot strand the first with nothing to remove it."""
        from amaze.render import nodes

        real_scratch = hostos.unique_scratch
        calls = []

        def second_one_fails(path, *args, **kwargs):
            calls.append(path)
            if len(calls) == 2:
                raise OSError(24, "Too many open files")
            return real_scratch(path, *args, **kwargs)

        hostos.unique_scratch = second_one_fails
        self.addCleanup(setattr, hostos, "unique_scratch", real_scratch)
        handler = nodes.NodeHandler.__new__(nodes.NodeHandler)
        with self.assertRaises(OSError):
            handler.save_asset_pair(
                os.path.join(self.dir, "LEAK.interface"),
                os.path.join(self.dir, "LEAK.mat"), "parms\n",
                lambda scratch: None)
        self.assertEqual(2, len(calls), "premise: the second call must have "
                         "been reached and failed")
        self.assertEqual(
            [], sorted(os.listdir(self.dir)),
            "the first scratch was left in the asset folder, where Clean "
            "Library has to decide whether it is an orphan")

    def test_preserving_an_unreadable_file_says_nothing_on_screen(self):
        """The helper RECORDS, the caller speaks - a line printed from inside is a second paragraph about one event."""
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

    def test_save_asset_pair_survives_houdini_s_own_writer(self):
        """THE REAL WRITER, not a lambda - `unique_scratch` pre-creates the file, and that Houdini's own writer overwrites a pre-created 0-byte one is the assumption nothing else here drives."""
        import hou
        from amaze.render import nodes

        parent = hou.node("/mat") or hou.node("/shop")
        if parent is None:
            self.skipTest("no /mat context in this build")
        holder = parent.createNode("subnet", "amaze_scratch_probe")
        self.addCleanup(holder.destroy)
        holder.createNode("null", "inside")
        handler = nodes.NodeHandler.__new__(nodes.NodeHandler)
        interface_path = os.path.join(self.dir, "REAL.interface")
        mat_path = os.path.join(self.dir, "REAL.mat")
        handler.save_asset_pair(
            interface_path, mat_path, "promoted parms\n",
            lambda scratch: holder.saveItemsToFile(
                holder.children(), scratch, save_hda_fallbacks=False))
        self.assertGreater(
            os.path.getsize(mat_path), 0,
            "Houdini's own writer wrote nothing into a pre-created scratch, "
            "which is the assumption unique_scratch(create=True) rests on")
        self.assertEqual([], self._leftovers(),
                         "the real writer left a scratch behind")

    def test_save_asset_pair_scratches_live_beside_their_destinations(self):
        """`os.rename` cannot cross drives, and this pair can live on another volume than the system temp dir."""
        directories = []
        real_replace = hostos.replace_file
        hostos.replace_file = lambda src, dst: (
            directories.append(os.path.dirname(os.path.abspath(src))),
            real_replace(src, dst))[1]
        self.addCleanup(setattr, hostos, "replace_file", real_replace)
        from amaze.render import nodes
        handler = nodes.NodeHandler.__new__(nodes.NodeHandler)
        handler.save_asset_pair(
            os.path.join(self.dir, "A.interface"),
            os.path.join(self.dir, "A.mat"), "parms\n",
            lambda scratch: open(scratch, "w").write("net\n"))
        self.assertEqual([os.path.abspath(self.dir)] * 2, directories)

    def test_a_failed_mat_write_promotes_neither_file(self):
        """Why the pair is one unit: a failed `.mat` write must not leave a NEW `.interface` beside a stale `.mat`. ▸p/asset-write-unit"""
        from amaze.render import nodes
        import hou

        handler = nodes.NodeHandler.__new__(nodes.NodeHandler)
        interface_path = os.path.join(self.dir, "ASSET2.interface")
        mat_path = os.path.join(self.dir, "ASSET2.mat")
        with open(interface_path, "w", encoding="utf-8") as handle:
            handle.write("the good old interface\n")
        with open(mat_path, "w", encoding="utf-8") as handle:
            handle.write("the good old network\n")

        def write_nothing(_scratch):
            return None             # exactly what a failed save looks like

        with self.assertRaises(hou.OperationFailed):
            handler.save_asset_pair(interface_path, mat_path,
                                    "a new interface\n", write_nothing)
        with open(interface_path, encoding="utf-8") as handle:
            self.assertEqual(
                "the good old interface\n", handle.read(),
                "the .interface was replaced although the .mat write "
                "failed - the pair is no longer written as one unit")
        with open(mat_path, encoding="utf-8") as handle:
            self.assertEqual("the good old network\n", handle.read())
        self.assertEqual([], self._leftovers(),
                         "the failed write left its scratch files behind")

    def test_concurrent_asset_pair_writers_never_mix(self):
        """The measured mixing, forced with a barrier rather than hoped for, so the headline claim is the assertion that goes red. ▸p/testing-can-fail"""
        from amaze.render import nodes

        hostos.replace_file = self._real_replace
        interface_path = os.path.join(self.dir, "RACE.interface")
        mat_path = os.path.join(self.dir, "RACE.mat")
        mixed = []
        raised = []
        scratches = {}
        both_half_written = threading.Barrier(2, timeout=30)

        def write(mark):
            handler = nodes.NodeHandler.__new__(nodes.NodeHandler)
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
                handler.save_asset_pair(interface_path, mat_path, body,
                                        write_mat)
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
            "the asset itself there is no .bak tier to recover from")
        self.assertEqual(2, len(scratches),
                         "premise: both writers must have reached the .mat")
        self.assertNotEqual(
            scratches["A"], scratches["B"],
            "two overlapping writers were handed the same scratch path, so "
            "they share one buffer by construction")
        self.assertEqual([], raised, "a concurrent write raised")
        for path in (interface_path, mat_path):
            with open(path, encoding="utf-8") as handle:
                marks = set(handle.read().replace("\n", ""))
            self.assertEqual(
                1, len(marks),
                "%s holds bytes from both writers" % os.path.basename(path))
        self.assertEqual([], self._leftovers(),
                         "a scratch file survived the race")

    def test_a_new_file_gets_exactly_what_a_plain_open_would_have(self):
        """Against `_DEFAULT_FILE_MODE`, never `!= 0o600` - the looser form passes for the wrong reason under a 077 umask. ▸p/testing-can-fail"""
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
        """PRESERVING THE MODE PRESERVES THE DAMAGE - matching the destination keeps an owner-only file owner-only forever. ▸r/atomic-writes"""
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
        """0600 EXACTLY is what mkstemp creates, so recognising it recognises our own bug and nothing else - any other narrowing was a decision and survives."""
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
                "repair is reaching past the one mode it is meant to know")


class PrefsSurvivesADamagedOrUnwritableFileTest(unittest.TestCase):
    """`settings.json` is read at panel construction and written from ordinary sidebar use, so both directions fail softly."""

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

    def test_a_top_level_list_does_not_kill_the_panel(self):
        """An exception here kills the panel during construction with no interface and no message, and a top level that is not an object has no `.get()` at all."""
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
        """The one writer that reported nothing on failure, with no caller wrapping it - a full disk lost every preference change in silence."""
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
            "a failed settings write left no trace at all")


class AFailedRotationSaysSoTest(unittest.TestCase):
    """No data is lost when the tier cannot rotate, but it stops advancing."""

    def test_a_rotation_failure_reaches_the_log(self):
        import shutil as shutil_mod

        directory = test_support.scratch_dir("amaze_rotate_")
        self.addCleanup(shutil_mod.rmtree, directory, ignore_errors=True)
        target = os.path.join(directory, "library.json")
        for name, body in ((target, '{"assets": []}'),
                           (target + ".bak-first", '{"assets": []}'),
                           (target + ".bak-1", '{"assets": [1]}')):
            with open(name, "w", encoding="utf-8") as handle:
                handle.write(body)

        def boom(*_args, **_kwargs):
            raise OSError(13, "Permission denied")

        original = hostos.shutil.copy2
        hostos.shutil.copy2 = boom
        self.addCleanup(setattr, hostos.shutil, "copy2", original)

        with test_support.captured_log() as log:
            hostos.snapshot_before_write(target)      # must not raise

        self.assertTrue(
            log.matching("the tier could not be rotated", "backup"),
            "the backup tier stopped advancing and nothing recorded it")


class NoContentWriterTargetsItsDestinationTest(unittest.TestCase):
    """A SOURCE-derived scan over the whole package, because the per-writer tests above are a LIST and asset content has no `.bak-*` tier to recover from. ▸p/guard-pinned-filename-list ▸r/atomic-writes"""

    SCRATCH_NAMES = {"scratch", "path", "tmp_mat", "tmp", "dest"}

    def _package_root(self):
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_every_saveItemsToFile_writes_to_a_scratch(self):
        import ast
        offenders = []
        root = self._package_root()
        for folder, _dirs, files in os.walk(root):
            if "tests" in folder.split(os.sep):
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
            "save that dies partway truncates content that has no backup "
            "tier to restore from:\n  " + "\n  ".join(offenders))


class MachineLocalHistoryTest(unittest.TestCase):
    """The `.bak-*` ring sits inside the synced tree it protects against, so a machine-local daily ledger is ADDED beside it, never instead of it. ▸r/atomic-writes"""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_hist_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "library.json")
        self.config = tempfile.mkdtemp(prefix="amaze_hist_cfg_")
        self.addCleanup(shutil.rmtree, self.config, ignore_errors=True)
        real_config = hostos.config_root
        hostos.config_root = lambda: self.config
        self.addCleanup(setattr, hostos, "config_root", real_config)

    def _write(self, payload):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def _entries(self):
        folder = hostos.history_root(self.path)
        if not os.path.isdir(folder):
            return []
        return sorted(os.listdir(folder))

    def test_the_entry_lands_outside_the_library_and_round_trips(self):
        self._write({"assets": [{"id": "A", "name": "gold"}]})
        entry = hostos.record_history(self.path)
        self.assertTrue(entry, "no history entry was written")
        self.assertFalse(
            os.path.abspath(entry).startswith(os.path.abspath(self.dir)),
            "the history entry is inside the library it protects - the "
            "same tree a sync client propagates corruption through")
        with gzip.open(entry, "rb") as fh:
            self.assertEqual({"assets": [{"id": "A", "name": "gold"}]},
                             json.loads(fh.read().decode("utf-8")))

    def test_one_entry_per_day_not_per_save(self):
        self._write({"assets": []})
        self.assertTrue(hostos.record_history(self.path))
        for _ in range(5):
            self._write({"assets": [{"id": "later"}]})
            self.assertEqual("", hostos.record_history(self.path),
                             "a second entry was written the same day")
        self.assertEqual(1, len(self._entries()))

    def test_a_file_that_does_not_parse_is_not_recorded(self):
        """Recording garbage spends the day's slot while the good state ages out behind it."""
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{ truncated")
        self.assertEqual("", hostos.record_history(self.path))
        self.assertEqual([], self._entries())

    def test_two_libraries_do_not_share_a_folder(self):
        other_dir = tempfile.mkdtemp(prefix="amaze_hist_other_")
        self.addCleanup(shutil.rmtree, other_dir, ignore_errors=True)
        self.assertNotEqual(
            hostos.history_root(self.path),
            hostos.history_root(os.path.join(other_dir, "library.json")),
            "two libraries write their history to one folder, so each "
            "overwrites the other's day")

    def test_old_entries_are_pruned_by_DATE_not_mtime(self):
        """The name carries the date the copy is OF, and a restore or a file copy rewrites mtime."""
        folder = hostos.history_root(self.path)
        os.makedirs(folder, exist_ok=True)
        made = []
        for day in range(1, 8):
            name = "library.json.2026-01-%02d.gz" % day
            full = os.path.join(folder, name)
            with gzip.open(full, "wb") as fh:
                fh.write(b"{}")
            made.append(name)
        os.utime(os.path.join(folder, made[0]), None)   # oldest, so mtime and date disagree
        hostos._prune_history(folder, "library.json", days=3)
        left = sorted(n for n in os.listdir(folder) if n.endswith(".gz"))
        self.assertEqual(made[-3:], left,
                         "pruning kept the wrong entries - it is following "
                         "mtime, which a restore or a copy rewrites")

    def test_a_save_records_history_without_being_asked(self):
        """Wired into the one chokepoint every database uses, so a new database cannot arrive without history."""
        self._write({"assets": []})
        hostos.snapshot_before_write(self.path)
        self.assertEqual(1, len(self._entries()),
                         "snapshot_before_write did not record a history "
                         "entry, so nothing outside the synced tree holds "
                         "yesterday's state")


class TwoPanesEditSettingsWithoutClobberTest(unittest.TestCase):
    """`panel.py` constructs a Prefs per pane tab, so two writers of `settings.json` is ordinary use and either pane's save erased the other's whole document."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_prefs_merge_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def _prefs(self):
        p = prefs.Prefs()
        p.path = self.dir
        p.load()
        return p

    def test_the_adoption_SURVIVES_the_next_save_from_the_same_pane(self):
        """One save was the whole lifetime of the merge, and closing Preferences saves twice - the sibling test above saves once per pane and stayed green throughout."""
        pane_a = self._prefs()
        pane_a.save()
        pane_b = self._prefs()

        pane_a.add_file_folder("/theirs/textures")
        pane_a.save()

        pane_b.thumbsize = 256
        pane_b.save()                       # adopts /theirs/textures
        pane_b.save()                       # <- this used to erase it

        check = prefs.Prefs()
        check.path = self.dir
        check.load()
        self.assertIn(
            "/theirs/textures", [str(f) for f in check.file_folders],
            "the second save from the same pane erased the folder the "
            "first one had just adopted - the merge repaired self.data "
            "only, and refresh_data rebuilds it from the attributes")
        self.assertEqual(256, check.thumbsize,
                         "pane B's own change did not land")

    def test_a_location_LABEL_saved_by_the_other_pane_survives(self):
        """Location decorations travel inside `file_location_records`, so a merge adopting the DERIVED keys writes into attributes nothing reads back."""
        pane_a = self._prefs()
        pane_a.save()
        pane_b = self._prefs()

        pane_a.add_file_folder("/theirs/textures")
        pane_a.set_file_folder_name("/theirs/textures", "Their Label")
        pane_a.save()

        pane_b.thumbsize = 256
        pane_b.save()

        check = self._prefs()
        keys = [path for path in check.file_folders
                if "theirs" in str(path)]
        self.assertTrue(keys, "the folder itself was clobbered - the "
                              "list merge has regressed too")
        names = dict(check.file_folder_names)
        self.assertEqual(
            "Their Label", names.get(keys[0], ""),
            "pane B's save dropped the label pane A had just written - "
            "the records merge adopted nothing")

    def test_every_collected_key_has_a_backing_attribute(self):
        """Every collected key must be reachable in BOTH shapes - flat while nobody is picked, nested under `users/<uid>/` once somebody is."""
        from amaze.core import keyed_store
        rules = keyed_store.store_for(keyed_store.SETTINGS).merge_rules
        flat = {key for key in rules if "/" not in key and key != "users"}
        nested = {key.split("/")[-1] for key in rules if "/" in key}
        self.assertEqual(
            set(), flat - nested,
            "a collected key is folded flat but not inside a user "
            "block - unreachable on any machine that has a user")
        self.assertEqual(
            set(), nested - flat,
            "a collected key is folded inside a user block but not "
            "flat - unreachable while nobody is picked")
        self.assertEqual("fields", rules.get("users"),
                         "a uid this pane has never seen must arrive "
                         "whole, or a second user is invisible")
        blank = prefs.Prefs()
        for attr in ("_file_folders", "_file_favorites",
                     "_file_location_records", "_users_blocks"):
            self.assertTrue(
                hasattr(blank, attr),
                "the fold is absorbed into %s, which a fresh Prefs "
                "does not have" % attr)

    def test_a_scalar_takes_the_saving_pane(self):
        """The merge must not turn scalars into a fight - the pane being touched wins the single-choice keys."""
        pane_a = self._prefs()
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
                         "the active editor's scalar lost")


class AHealthyFileRepairsABrokenFloorTest(unittest.TestCase):
    """`.bak-first` is write-once forever, so a floor minted from a truncated file is worse than no floor at all."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_floor_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, "library.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"assets": [{"id": "GOOD"}]}, fh)
        hostos._session_snapshots.pop(self.path, None)
        self.addCleanup(hostos._session_snapshots.pop, self.path, None)

    def _floor(self):
        with open(self.path + ".bak-first", encoding="utf-8") as fh:
            return fh.read()

    def test_a_garbage_floor_is_replaced_by_a_healthy_file(self):
        with open(self.path + ".bak-first", "w", encoding="utf-8") as fh:
            fh.write("{ truncated garbage")
        hostos.snapshot_before_write(self.path)
        self.assertIn("GOOD", self._floor(),
                      "the permanent restore floor is still garbage - "
                      "the one copy that never rotates is the one that "
                      "never worked")

    def test_a_parseable_floor_with_different_content_is_never_touched(self):
        """The control - replacing a HEALTHY floor because it differs is the floor failing at its whole job."""
        with open(self.path + ".bak-first", "w", encoding="utf-8") as fh:
            json.dump({"assets": [{"id": "OLD-STATE"}]}, fh)
        hostos.snapshot_before_write(self.path)
        self.assertIn("OLD-STATE", self._floor(),
                      "a parseable .bak-first was overwritten - the "
                      "earliest state is gone")


class SnapshotsAreThrottledNotOncePerProcessTest(unittest.TestCase):
    """A once-per-session gate gives the rolling `.bak-N` ring one state per launch, so the ring mostly holds air."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_throttle_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.path = os.path.join(self.dir, "library.json")
        hostos._session_snapshots.pop(self.path, None)
        self.addCleanup(hostos._session_snapshots.pop, self.path, None)

    def _write_state(self, count):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"assets": [{"id": "a%d" % i} for i in range(count)]},
                      fh)

    def _tiers(self):
        return sorted(n for n in os.listdir(self.dir) if ".bak-" in n)

    def test_states_past_the_interval_each_get_a_snapshot(self):
        for number, count in enumerate((1, 2, 3, 4), 1):
            self._write_state(count)
            hostos.snapshot_before_write(self.path)
            # Backdate the stamp - monotonic time itself cannot be moved.
            hostos._session_snapshots[self.path] -= (
                hostos.SNAPSHOT_INTERVAL + 1)
        tiers = self._tiers()
        self.assertIn("library.json.bak-first", tiers)
        self.assertEqual(
            {"library.json.bak-1", "library.json.bak-2",
             "library.json.bak-3", "library.json.bak-first"},
            set(tiers),
            "distinct states past the interval did not each earn a "
            "snapshot - the ring holds one state per launch again: %s"
            % tiers)

    def test_inside_the_interval_no_second_snapshot(self):
        self._write_state(1)
        hostos.snapshot_before_write(self.path)
        before = self._tiers()
        self._write_state(2)
        hostos.snapshot_before_write(self.path)   # seconds later
        self.assertEqual(before, self._tiers(),
                         "a save storm can chew all three slots inside "
                         "a minute")

    def test_identical_content_does_not_consume_a_slot(self):
        self._write_state(3)
        hostos.snapshot_before_write(self.path)
        hostos._session_snapshots[self.path] -= (
            hostos.SNAPSHOT_INTERVAL + 1)
        hostos.snapshot_before_write(self.path)   # same bytes
        tiers = self._tiers()
        self.assertNotIn("library.json.bak-2", tiers,
                         "an identical state consumed a rotation slot")


class TheLibraryUserIsTheOneIdentityTest(unittest.TestCase):
    """`library_user` is WHO this is - one field keying per-user storage and signing versions, and it is never harvested. ▸p/identity-is-chosen"""

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

    def test_an_existing_version_author_is_adopted(self):
        """The adopted name BECOMES the user; the retired key is dropped on the next save."""
        home = self._home()
        self._write_settings(home, {"version_author": "Plum"})
        p = self._prefs_at(home)
        self.assertEqual("Plum", p.library_user)
        p.save()
        with open(os.path.join(home, "settings.json"),
                  encoding="utf-8") as handle:
            stored = json.load(handle)
        self.assertNotIn("version_author", stored,
                         "the retired key survived a save")
        self.assertEqual("Plum", stored.get("library_user"))

    def test_no_identity_source_touches_the_author_path(self):
        """Source-derived ban on the account and machine name, walking EVERY module of the package plus `core/users.py`, never the one that used to hold the risk. ▸p/identity-is-chosen ▸p/guard-pinned-filename-list"""
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
                    "%s appears in %s - an identity can be harvested "
                    "into a user's name" % (banned, name))
        self.assertIn("prefs.py", checked)
        self.assertIn("persistence.py", checked)
        self.assertIn("users.py", checked)


class TheUserIsAUidWithANameTest(unittest.TestCase):
    """A user is a UID with a NAME beside it - the asset convention applied to people, so a rename relinks one label and moves no data. ▸p/identity-is-chosen"""

    def _prefs(self):
        from amaze.tests import test_support
        return test_support.fixture_prefs(self)

    def test_creating_a_user_answers_a_uid_not_the_name(self):
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

    def test_preferences_says_a_name_is_taken_and_makes_nobody(self):
        import types
        import hou
        from amaze import messages
        from amaze.core import users
        from amaze.dialogs import base_dialog, prefs_dialog
        p = self._prefs()
        users.create(p, "Plum")
        dialog = prefs_dialog.PrefsDialog(p, panel=None)
        self.addCleanup(dialog.deleteLater)
        said = []

        class Named:
            canceled = False
            name = "plum"

            def __init__(self, *_a, **_k):
                pass

            def exec(self):
                pass

        ui = types.SimpleNamespace(displayMessage=lambda text, **_k: said.append(text))
        with mock.patch.object(base_dialog, "NameDialog", Named), \
                mock.patch.object(hou, "ui", ui, create=True):
            dialog._ask_create_library_user()
        self.assertEqual([messages.USER_NAME_TAKEN % "plum"], said)
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
                      "the rename minted a second user")
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

    def test_a_name_left_in_the_pointer_is_nobody(self):
        """A NAME in the pointer, as the first builds wrote it, names nobody, and nobody is made of it."""
        from amaze.core import users
        p = self._prefs()
        p.library_user = "Plum"
        self.assertIsNone(users.current(p))
        self.assertEqual({}, users.all_users(p))

    def test_nobody_asks_or_resolves_and_none_makes_a_user(self):
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
                          "it minted a second identity instead of "
                          "asking which user this is")

        p = self._prefs()
        uid = users.create(p, "Plum")
        p.library_user = uid
        self.assertEqual(users.RESOLVED, users.first_run_state(p))
        self.assertEqual(uid, users.current(p))

    def test_versions_sign_with_the_readable_name(self):
        """The UID identifies, the NAME signs - a UID stem is unreadable and matches nothing already on disk."""
        from amaze.core import users, versions
        p = self._prefs()
        uid = users.create(p, "Plum")
        p.library_user = uid
        self.assertEqual("Plum", versions.writer_tag(p))


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


A_USER = "a1b2c3d4e5f60718293a4b5c6d7e8f90"  # minted shape: the product tags with uuid4().hex only, and only that shape reads back as an owner
B_USER = "90f8e7d6c5b4a3928170f6e5d4c3b2a1"


class AStoreCanTagItsKeysWithAnOwnerTest(unittest.TestCase):
    """A store may declare its keys TAGGED with the user and the ENGINE does the tagging - asserted against a `Spec(...)` this test builds, never a registered one, which would put a fictional file in front of Repair for every later test."""

    SEP = "|"

    def setUp(self):
        from amaze.core import keyed_store
        self.dir = tempfile.mkdtemp(prefix="amaze_tagged_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        keyed_store.release()
        self.addCleanup(keyed_store.release)

    def _spec(self, tagged=True):
        from amaze.core import keyed_store
        return keyed_store.Spec(
            filename="tagtest.json", payload="entries",
            keyspace=keyed_store.KEY_PATH, label="Tag test", noun="entry",
            normalise=lambda value: {"on": True} if value else {},
            user_tagged=tagged)

    def _prefs(self, user=""):
        class _P:
            pass
        p = _P()
        p.dir = self.dir
        p.library_user = user
        return p

    def _store(self, user="", tagged=True):
        from amaze.core import keyed_store
        return keyed_store.open_store(self._spec(tagged), self._prefs(user))

    def _on_disk(self):
        with open(os.path.join(self.dir, "tagtest.json"),
                  encoding="utf-8") as handle:
            return json.load(handle)["entries"]

    def _plant(self, *keys):
        """A file written the way a build BEFORE the tag wrote one."""
        with open(os.path.join(self.dir, "tagtest.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"entries": {key: {"on": True} for key in keys}},
                      handle)

    def test_the_stored_key_carries_the_uid(self):
        """`<uid>|<key>` on disk, split on the FIRST separator only - a uuid4 hex cannot contain one, a path can."""
        self._store(A_USER).set("~/a|b.exr", True)
        keys = list(self._on_disk())
        self.assertEqual(1, len(keys))
        tag, _sep, rest = keys[0].partition(self.SEP)
        self.assertEqual(A_USER, tag, "key %r is not tagged" % keys[0])
        self.assertEqual("~/a|b.exr", rest,
                         "a separator inside the KEY was eaten")

    def test_no_user_stores_nothing_rather_than_a_blank_bucket(self):
        """An empty tag is not a shared user, it is an absent one."""
        from amaze.core import keyed_store
        written = self._store("").set("~/a.exr", True)
        self.assertFalse(written, "an entry was filed with no user")
        self.assertEqual(keyed_store.REASON_NO_USER, written.reason)
        self.assertFalse(self._store("").has("~/a.exr"))

    def test_all_is_scoped_and_everyones_is_not(self):
        """`all()` is what is MINE and what a section paints; `everyones()` is the unscoped read, for repair and migration only."""
        from amaze.core import keyed_store
        self.assertTrue(self._store(A_USER).set("~/mine.exr", True))
        self.assertTrue(self._store(A_USER).has("~/mine.exr"))
        keyed_store.release()
        self._store(B_USER).set("~/theirs.exr", True)
        self.assertFalse(
            self._store(B_USER).has("~/mine.exr"),
            "the other user's entry is showing - the tag is not keeping "
            "them apart")
        keyed_store.release()
        store = self._store(A_USER)
        self.assertTrue(store.has("~/mine.exr"),
                        "switching back lost the first user's entry")
        self.assertEqual(["~/mine.exr"], sorted(store.all()),
                         "all() is not scoped to this user")
        self.assertEqual(2, len(store.everyones()),
                         "everyones() cannot see across people")

    def test_a_row_from_before_the_store_had_owners_is_dropped(self):
        """A pre-owner row is REMOVED, not adopted - nothing on it says whose it was, and adopting would give one person everybody's entries."""
        self._plant("~/old.exr")
        store = self._store(A_USER)
        self.assertFalse(store.has("~/old.exr"),
                         "an entry from before the store had owners is "
                         "still showing")
        self.assertEqual({}, store.all())
        self.assertEqual({}, store.everyones(),
                         "the row was kept aside rather than dropped")
        store.set("~/mine.exr", True)
        self.assertEqual([A_USER + self.SEP + "~/mine.exr"],
                         sorted(self._on_disk()),
                         "the untagged row was written back after being "
                         "dropped")

    def test_asking_for_nothing_is_not_a_refusal(self):
        """DOING NOTHING CANNOT FAIL - an empty write answers UNCHANGED, or a caller checking the answer reads a failure into an empty list."""
        from amaze.core import keyed_store
        store = self._store("")
        for written, what in ((store.update({}), "update"),
                              (store.rekey({}), "rekey"),
                              (store.retire([]), "retire")):
            self.assertTrue(written, "an empty %s was refused" % what)
            self.assertEqual(keyed_store.REASON_UNCHANGED, written.reason,
                             "an empty %s did not answer unchanged" % what)

    def test_an_untagged_store_is_completely_unaffected(self):
        """THE CONTROL: with `user_tagged` false the engine behaves exactly as it did, including for a prefs carrying no user."""
        from amaze.core import keyed_store
        store = self._store("", tagged=False)
        self.assertTrue(store.set("~/a.exr", True))
        self.assertTrue(store.has("~/a.exr"))
        self.assertEqual(["~/a.exr"], sorted(store.all()))
        self.assertEqual(store.all(), store.everyones())
        keyed_store.release()
        self._plant("~/old.exr")
        self.assertTrue(self._store("", tagged=False).has("~/old.exr"),
                        "an untagged store dropped a row it should keep")


class SandboxRefusesAWriteOutsideTempTest(unittest.TestCase):
    """The one function every JSON write goes through refuses on its own behalf when a run says it may touch only temporary files. ▸p/hand-run-script-is-unguarded"""

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

    def test_a_write_outside_temp_is_refused_loudly(self):
        self.arm()
        outside = os.path.join(os.path.expanduser("~"), "amaze_sandbox_probe.json")
        self.assertFalse(os.path.exists(outside), "the fixture path exists")
        with self.assertRaises(hostos.SandboxRefused):
            hostos.write_json_atomic(outside, {"a": 1})
        self.assertFalse(
            os.path.exists(outside),
            "the refusal did not happen before the write - the file is "
            "on disk, which is the whole thing this prevents")

    def test_a_write_inside_temp_still_lands(self):
        self.arm()
        inside = os.path.join(self.tmp, "fine.json")
        hostos.write_json_atomic(inside, {"a": 1})
        with open(inside, encoding="utf-8") as handle:
            self.assertEqual({"a": 1}, json.load(handle))

    def test_unarmed_it_does_nothing_at_all(self):
        """Nothing in the product sets the variable, and a guard on by accident would refuse the user's own saves."""
        os.environ.pop(hostos.SANDBOX_VAR, None)
        self.assertFalse(hostos.sandboxed())
        outside = os.path.join(self.tmp, "..", os.path.basename(self.tmp),
                               "unarmed.json")
        hostos.write_json_atomic(outside, {"a": 1})
        self.assertTrue(os.path.exists(outside))
        hostos.check_sandbox("/anywhere/at/all.json")


class SandboxRefusesEveryPrimitiveTest(unittest.TestCase):
    """Every shared write primitive refuses a path outside the temp dir, not only the JSON door."""

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

    def _refused(self, call, *args):
        before = sorted(os.listdir(self.outside))
        with self.assertRaises(hostos.SandboxRefused):
            call(*args)
        self.assertEqual(before, sorted(os.listdir(self.outside)),
                         "%s wrote outside the temp dir before refusing"
                         % call.__name__)

    def _planted(self, name, text):
        path = os.path.join(self.outside, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        self.addCleanup(hostos._session_snapshots.pop, path, None)
        return path

    def _inside_file(self):
        path = os.path.join(self.inside, "scratch.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{}")
        return path

    def test_a_scratch_beside_an_outside_path_is_refused(self):
        target = os.path.join(self.outside, "a.json")
        self._refused(hostos.unique_scratch, target)

        def through_the_context(path):
            with hostos.scratch_beside(path):
                pass
        self._refused(through_the_context, target)

    def test_a_promote_or_replace_onto_an_outside_path_is_refused(self):
        target = os.path.join(self.outside, "a.json")
        self._refused(hostos.promote_scratch, self._inside_file(), target)
        self._refused(hostos.replace_file, self._inside_file(), target)

    def test_the_snapshot_copies_are_refused(self):
        healthy = self._planted("lib.json", '{"assets": []}')
        broken = self._planted("bad.json", "{ truncated")
        self._refused(hostos.snapshot_before_write, healthy)
        self._refused(hostos.seed_restore_floor, healthy)
        self._refused(hostos.preserve_unreadable, broken)

    def test_a_history_entry_outside_is_refused(self):
        real_config = hostos.config_root
        hostos.config_root = lambda: self.outside
        self.addCleanup(setattr, hostos, "config_root", real_config)
        source = os.path.join(self.inside, "library.json")
        with open(source, "w", encoding="utf-8") as handle:
            handle.write('{"assets": []}')
        self._refused(hostos.record_history, source)

    def test_a_quarantine_move_outside_is_refused(self):
        from amaze.core import quarantine
        real_config = hostos.config_root
        hostos.config_root = lambda: self.outside
        self.addCleanup(setattr, hostos, "config_root", real_config)
        library = os.path.join(self.inside, "library")
        os.makedirs(os.path.join(library, "mat"))
        leftover = os.path.join(library, "mat", "LEFTOVER.mat")
        with open(leftover, "w", encoding="utf-8") as handle:
            handle.write("x")
        self._refused(quarantine.quarantine_file, library, leftover)
        self.assertTrue(os.path.exists(leftover),
                        "the refused move still took the file")

    def test_a_cache_folder_made_outside_is_refused(self):
        self.addCleanup(hostos.set_cache_override, hostos._cache_override)
        hostos.set_cache_override(os.path.join(self.outside, "cache"))
        self._refused(hostos.cache_root)


class SandboxKeepsThePerUserFoldersInTempTest(unittest.TestCase):
    """Armed, the settings, cache and log folders stand in temp - a suite save's history lands there."""

    def setUp(self):
        original = os.environ.get(hostos.SANDBOX_VAR)
        if original is None:
            self.addCleanup(os.environ.pop, hostos.SANDBOX_VAR, None)
        else:
            self.addCleanup(
                os.environ.__setitem__, hostos.SANDBOX_VAR, original)

    def _assert_in_temp(self):
        temp = os.path.realpath(tempfile.gettempdir()) + os.sep
        library = os.path.join(temp, "library", "library.json")
        for label, path in (("settings", hostos.config_root()),
                            ("cache", hostos.cache_root()),
                            ("log", hostos.log_root()),
                            ("history", hostos.history_root(library))):
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

    def test_the_redirect_survives_a_reload_of_hostos(self):
        import importlib
        os.environ[hostos.SANDBOX_VAR] = "1"
        before = hostos.config_root()
        importlib.reload(hostos)
        self.assertEqual(before, hostos.config_root(),
                         "a reload moved the settings folder")
        self._assert_in_temp()

    def test_unarmed_the_folders_are_the_users_own(self):
        """Nothing in the product arms it, so the stand-in must never answer for a real session."""
        held = os.environ.get(hostos.SANDBOX_HOME_VAR)
        if held is None:
            self.addCleanup(os.environ.pop, hostos.SANDBOX_HOME_VAR, None)
        else:
            self.addCleanup(
                os.environ.__setitem__, hostos.SANDBOX_HOME_VAR, held)
        os.environ.pop(hostos.SANDBOX_VAR, None)
        os.environ[hostos.SANDBOX_HOME_VAR] = tempfile.gettempdir()
        self.assertEqual("", hostos.sandbox_home(),
                         "an unarmed run answered the stand-in folder")


class OnePathHasOneSpelling(unittest.TestCase):
    """Two encoders write the same folder into two files, and a `$AMAZE/..` walk breaks the moment the install moves where `~` survives it - both decoders read both spellings, so nothing migrates."""

    def _cases(self):
        from amaze.helpers import hostos
        amaze = os.environ.get("AMAZE", "")
        home = os.path.expanduser("~")
        cases = [os.path.join(home, "textures", "wood"),
                 home,
                 "/Volumes/Share/textures"]
        if amaze:
            # The divergent shape: shares a subtree with the install, not under it.
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

    def test_the_old_walking_spelling_is_still_read(self):
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
        """`directory` is stored WITH one, and the home half is built CANONICALLY - gluing a POSIX literal onto a Windows `expanduser` mints a spelling no encoder here can emit."""
        from amaze.prefs import persistence
        for path in (test_support.posix_path(os.path.expanduser("~"))
                     + "/Cloud/lib/",
                     "/Volumes/Share/lib/"):
            self.assertEqual(
                path, persistence._decode_path(
                    persistence._encode_path(path)),
                "the library pointer lost its trailing separator")


class ImportingTheHarnessArmsTheSandboxTest(unittest.TestCase):
    """A test started without the runner is armed by `test_support`. ▸p/hand-run-script-is-unguarded"""

    CHILD = ("from amaze.core import database\n"
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
                         "the bare run died: %s" % result.stderr[-800:])
        return dict(line.split("=", 1) for line in result.stdout.splitlines()
                    if line.startswith(("ARMED=", "SETTINGS=")))

    def test_a_module_run_without_the_runner_is_armed(self):
        said = self._bare_run()
        self.assertEqual(
            "True", said.get("ARMED"),
            "a test module started without start_test.sh is not armed, so "
            "it can write the user's real settings folder")
        self.assertNotEqual(
            os.path.realpath(hostos.real_config_root()),
            os.path.realpath(said.get("SETTINGS", "")),
            "the bare run's settings folder is the user's own")


class TheSandboxStaysArmedForTheSuiteTest(unittest.TestCase):
    """The sentinel: `AMAZE_SANDBOX` is armed for the WHOLE process, so a pop-as-cleanup leaves every later test able to write live data. Named to sort behind the guard class it holds."""

    def test_the_armed_state_survived_the_sandbox_tests(self):
        self.assertTrue(
            hostos.sandboxed(),
            "a sandbox test disarmed the process and never re-armed it "
            "- every test after this module can now write live data")


class TextFilesAreTheSameBytesOnEveryOS(unittest.TestCase):
    """Text mode on Windows encodes by the locale and writes `\\r\\n`, so a file one Mac and one PC both save flips under the sync and a byte compare calls it changed. Read from the SOURCE, so a new open() is held to it too. ▸r/platform-files"""

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
        self.assertGreaterEqual(len(self._text_opens()), 40,    # ▸p/vacuous-register
                                "the scan stopped matching, so its silence means nothing")

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
