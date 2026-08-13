"""The write path: no reader may ever see a half-written database.

The bug this pins was not theoretical and was not a truncation. Both
database writers used a FIXED scratch name, `path + ".tmp"`, so two
savers of the same file shared one buffer. Measured 2026-07-29, two
processes x 600 saves through the old shape:

    clean = 3414    MIXED-CONTENT = 794    UNPARSEABLE = 790

The 790 unparseable reads are the harmless half - JSON announces a
truncation loudly, and the codebase already refuses on a parse failure.
The 794 are the dangerous half: they PARSED, and they held records from
BOTH writers, leaving the destination larger than either document. A
corruption that parses is a corruption nothing downstream can detect.

So the test that matters is not "does it write a valid file" - the old
code did that most of the time. It is "can two concurrent writers ever
share a scratch file", which is a property of the NAME.
"""

import gzip
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest

# A subset run led by this module aborts with SIGABRT ("QWidget: Must
# construct a QApplication before a QWidget") before unittest can print
# its FAIL lines - the full suite never sees it because another module
# builds the app first. Same preamble as test_keyed_store.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402

_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze.helpers import hostos                         # noqa: E402
from amaze.prefs import prefs                            # noqa: E402
from amaze.tests import test_support                     # noqa: E402,F401

#: Whether the PROCESS arrived armed - captured at import, before any
#: test has run, because discovery imports every module first. The
#: sentinel class at the bottom holds the sandbox tests to putting this
#: state back.
_SANDBOX_ARMED_AT_IMPORT = hostos.sandboxed()


class AtomicWriteTest(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_atomic_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, "library.json")

    def _leftovers(self):
        return [n for n in os.listdir(self.dir)
                if n != os.path.basename(self.path)]

    def test_it_writes_readable_json(self):
        hostos.write_json_atomic(self.path, {"assets": [{"id": "a"}]})
        with open(self.path, encoding="utf-8") as fh:
            self.assertEqual({"assets": [{"id": "a"}]}, json.load(fh))

    def test_the_scratch_name_is_unique_per_writer(self):
        """THE regression. A fixed name is what let two savers collide.

        Captured from inside the write, because the scratch exists only
        for the moment between creation and the rename.
        """
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
        """The measured failure, reproduced in-process.

        Each writer writes a document that is entirely its own. Any
        result holding both writers' marks is the silent corruption.
        """
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

    def test_no_scratch_file_survives_a_success(self):
        hostos.write_json_atomic(self.path, {"ok": True})
        self.assertEqual([], self._leftovers(),
                         "a scratch file was left in the library")

    def test_no_scratch_file_survives_a_failure(self):
        """An unserialisable value must not litter the library.

        The old shape left `library.json.tmp` behind, and a later reader
        scanning the directory then has to know to ignore it - which is
        exactly the kind of unowned file that got 8 live assets called
        orphans on 2026-07-29.
        """
        with self.assertRaises(TypeError):
            hostos.write_json_atomic(self.path, {"bad": object()})
        self.assertEqual([], self._leftovers(),
                         "a failed write left its scratch file behind")

    def test_a_failed_write_does_not_damage_the_existing_file(self):
        hostos.write_json_atomic(self.path, {"good": 1})
        with self.assertRaises(TypeError):
            hostos.write_json_atomic(self.path, {"bad": object()})
        with open(self.path, encoding="utf-8") as fh:
            self.assertEqual({"good": 1}, json.load(fh),
                             "a failed write replaced a good file")

    def test_the_scratch_lives_beside_the_destination(self):
        """os.rename cannot cross drives on any OS (research.md, Windows
        audit), so a scratch in the system temp dir would make every save
        fail on a machine whose library is on another volume."""
        seen = []
        real_replace = hostos.replace_file
        hostos.replace_file = lambda src, dst: (
            seen.append(os.path.dirname(os.path.abspath(src))),
            real_replace(src, dst))[1]
        self.addCleanup(setattr, hostos, "replace_file", real_replace)
        hostos.write_json_atomic(self.path, {"x": 1})
        self.assertEqual([os.path.abspath(self.dir)], seen)


class EveryScratchWriterIsUniqueTest(unittest.TestCase):
    """The property is a property of the NAME, so it is testable per
    writer without reproducing a race.

    Four writers had grown their own fixed-name version of the atomic
    write: prefs.py (`final + ".tmp"`), library_policy.py and
    tile_icons.py (both `path + ".writing"`), and - the one that matters
    most - render/nodes.py's save_asset_pair, which writes the ASSET
    rather than an index of assets, into a directory with no `.bak-*`
    tier at all.

    Each test below drives the REAL writer, not the helper it now calls:
    a test of hostos alone would stay green through a call site that
    quietly kept its own fixed name, which is exactly the bug.
    """

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
        # And it still round-trips - a scratch-name fix that broke the
        # setting would be worse than the defect.
        self.assertFalse(library_policy.allow_overwrite(self.dir),
                         "the last written value was not read back")

    def test_tile_icons_uses_a_unique_scratch(self):
        from amaze.core import keyed_store, tile_icons

        class _Prefs:
            """Only what tile_icons reads for the override path. NOT a
            real Prefs: one built under hython resolves $AMAZE to the live
            install, which is how a test overwrote real settings once."""

            def __init__(self, directory):
                self.dir = directory
                self.img_dir = "img/"
                self.img_ext = ".png"

        prefs = _Prefs(self.dir + os.sep)
        tile_icons.forget_overrides()
        self.addCleanup(tile_icons.forget_overrides)
        # Through the ENGINE's own resolver, not a private in
        # tile_icons: the store's path policy moved to
        # keyed_store.open_store on 2026-08-03, which is the point -
        # one place composes it for every keyed side table.
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
        """THE ONE THAT MATTERS MOST. `.mat`/`.interface` IS the asset,
        and mat/ has no `.bak-*` tier, so a mixture of two writers is not
        a recoverable inconsistency - it is a material that no longer
        exists."""
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
        # BOTH destinations, and both must have gone through their own
        # scratch: one shared name for the pair would be just as wrong.
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
        """The LIVE case of the shared-buffer defect rather than the exotic
        one: the thumbnail cache directory is derived from a size and a
        prefix, nothing per-process, so two Houdini sessions browsing
        images write this file through the same path."""
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
        """A cache file's bytes are a contract too: reformatting it would
        rewrite every manifest on every machine for no reason. json.dump
        with no indent is what this wrote before."""
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
        """Two fetches of one asset - two panes, or a retry racing a slow
        first attempt - shared `dest_path + ".part"`, and the `finally`
        then removed whichever copy was still there regardless of who was
        writing it. That is the RAISING half of the same defect, landing on
        a texture where the truncation check is the only thing between a
        partial file and a material that renders wrong for good."""
        from amaze.core import matx_sources
        import io

        dest = os.path.join(self.dir, "texture.png")
        body = b"PNG bytes" * 64

        class _Resp(io.BytesIO):
            """_request RETURNS the response (used as `with _request(url)
            as resp`), it is not a context-manager factory - BytesIO
            already supports the protocol."""
            headers = {"Content-Length": str(len(body))}

        real_request = matx_sources._request
        matx_sources._request = lambda _url: _Resp(body)
        self.addCleanup(setattr, matx_sources, "_request", real_request)
        # CAUGHT MID-FLIGHT, through the progress callback the real UI
        # passes. Listing the directory afterwards proves nothing: the
        # `finally` removes the scratch either way, so the first version of
        # this test stayed green with the fixed `.part` name restored. The
        # name only exists while the transfer is running.
        scratches = set()

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
        """Two sessions capturing the same scene share `out`, which is
        derived from the hip file's path - so the fixed `.capturing` name
        was one shared buffer, and for a PNG a mixture is a decode failure
        the user is told about as a blank frame.

        create=False here, unlike every other caller: Houdini writes this
        file and saveThumbnailFromViewer needs a live scene viewer, so it
        cannot be measured against a pre-created one from a headless test.
        The extension still has to survive - Houdini picks the image FORMAT
        from it, and an earlier `.new` suffix made it write PIC2 bytes into
        a file everything downstream read as a PNG."""
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

    def test_the_capture_call_site_uses_the_shared_naming_helper(self):
        """SOURCE-DERIVED, because capture_thumbnail needs a live scene
        viewer and cannot be driven headlessly at all - and the helper above
        proves nothing about a call site that quietly builds its own name
        again. The property is a DECISION but it is not reachable at
        runtime, which is exactly the case practice ▸ source-derived tests
        keeps them for. Comments stripped first: an earlier test in this
        project failed on the comment documenting the fix it checked."""
        import inspect
        from amaze.core import scene_captures

        source = inspect.getsource(scene_captures.capture_thumbnail)
        body = "\n".join(line.split("#")[0]
                         for line in source.splitlines())
        assigns = [line.strip() for line in body.splitlines()
                   if line.strip().startswith("scratch =")]
        self.assertEqual(
            1, len(assigns),
            "capture_thumbnail no longer has exactly one scratch name - "
            "this test cannot say which one Houdini is handed (%r)" % assigns)
        # STARTSWITH on the right-hand side, not `in` on the line. `in`
        # passed for `_legacy_capture_scratch(out)`, which CONTAINS
        # "_capture_scratch(" - the substring trap, caught by the sabotage
        # pass and not by reading the test.
        called = assigns[0].split("=", 1)[1].strip()
        self.assertTrue(
            called.startswith("_capture_scratch("),
            "capture_thumbnail builds its own scratch name instead of "
            "going through the helper, so the unique-name rule and the "
            "extension rule are both back in play here (%r)" % called)

    def test_a_scratch_is_not_leaked_when_the_second_one_cannot_be_made(self):
        """Both scratches are created INSIDE the try, so the cleanup covers
        both. With the first call outside it, a failure of the SECOND - a
        full directory, no descriptors left - left the first scratch in
        mat/ with nothing to remove it, which is precisely the unowned file
        in the library directory that got 8 live assets called orphans."""
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
        """The helper RECORDS; the caller speaks. Every caller of
        preserve_unreadable already prints a full paragraph about the file
        it could not read and names the copy - or does not - from what this
        returned, so a printed line from inside was a second paragraph
        about one event, in vocabulary the reader cannot act on
        separately. snapshot_before_write chose the same policy 60 lines
        away in the same file; this was the outlier."""
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
        """THE REAL WRITER, not a lambda. unique_scratch pre-creates the
        file, which is what makes the name safe to hold - and every other
        test here hands save_asset_pair a callback that writes with a plain
        open(). All six production call sites pass hou.Node.saveItemsToFile,
        so the assumption that Houdini's writer overwrites a pre-created
        0-byte file was the one thing in this step nothing drove."""
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
        """os.rename cannot cross drives on any OS, and this pair can be
        written to a library on another volume than the system temp dir."""
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
        """The reason the pair is written as one unit at all. A .mat write
        that fails must not leave the NEW .interface beside a stale .mat -
        verified once by forcing saveItemsToFile to fail, which rewrote
        the .interface (57177 bytes against the old 57023) and left the
        previous good asset unrecoverable."""
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
        """The measured failure shape, applied to the asset itself, and
        MADE DETERMINISTIC so the headline claim is the assertion that goes
        red.

        The first version of this test raced two writers and then read the
        destinations. It went red under the fixed-name sabotage - but on
        `a concurrent write raised`, because one writer's cleanup removes
        the scratch the other is about to rename, and the mixed-content
        assertion below it never executed at all. A test whose stated claim
        is never reached is an unverified claim, however green the run.

        So the interleave is FORCED with a barrier instead of hoped for.
        Each writer stops half way through its own scratch, waits for the
        other to reach the same point, finishes, and then reads back the
        file it was given. With a scratch name per writer that read can
        only ever hold that writer's own mark. With one shared name the
        second writer's open() truncates the first's work and both then
        write on at their own offsets, so the first writer reads back the
        second's bytes - the exact silent, parseable mixture measured
        cross-process at 344 of 4800 reads, here with no sampling luck
        involved.
        """
        from amaze.render import nodes

        # The real replace_file, not setUp's capturing wrapper - a list
        # appended from two threads is not what this test is about.
        hostos.replace_file = self._real_replace
        interface_path = os.path.join(self.dir, "RACE.interface")
        mat_path = os.path.join(self.dir, "RACE.mat")
        mixed = []
        raised = []
        scratches = {}
        both_half_written = threading.Barrier(2, timeout=30)

        def write(mark):
            handler = nodes.NodeHandler.__new__(nodes.NodeHandler)
            body = (mark * 79 + "\n") * 256          # ~20KB, both files
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
        # THE HEADLINE FIRST, so it is the assertion that fails.
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

    def test_an_atomic_write_keeps_the_destination_s_permissions(self):
        """mkstemp creates at 0600, which is right for a scratch file in
        /tmp and wrong for the file it becomes. A shared library whose
        library.json and .mat files silently turned owner-only would stop
        being readable by the other person using it, with nothing in the
        app saying why."""
        if hostos.is_windows():
            self.skipTest("POSIX permission bits are not the model here")
        path = os.path.join(self.dir, "library.json")
        hostos.write_json_atomic(path, {"assets": []})
        os.chmod(path, 0o664)
        hostos.write_json_atomic(path, {"assets": [{"id": "a"}]})
        self.assertEqual(
            0o664, os.stat(path).st_mode & 0o777,
            "the save narrowed the file's permissions - anyone else "
            "working from this library just lost access to it")

    def test_a_new_file_gets_exactly_what_a_plain_open_would_have(self):
        """Against _DEFAULT_FILE_MODE, not against `!= 0o600`. The looser
        form passes for the wrong reason on any machine whose umask is 077,
        where the correct answer IS 0600 - so it would have gone red on a
        colleague's laptop while proving nothing on this one."""
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
        """PRESERVING THE MODE PRESERVES THE DAMAGE. write_json_atomic went
        through mkstemp with no chmod for a while, so every file it wrote
        in that window became owner-only - and "match the destination"
        would then keep it owner-only for every future save, forever.
        Measured on the real library, 2026-07-30: library.json 0600 and
        code.json 0600 (both written by that code) against cops.json 0644
        and gradients.json 0666 written before it. On a shared library the
        second person can open neither."""
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
        """The accept path, and the residual this fix accepts knowingly.
        0600 EXACTLY is what mkstemp creates with, so recognising it
        recognises our own bug - and nothing else. Any other narrowing is
        somebody's decision and survives."""
        if hostos.is_windows():
            self.skipTest("POSIX permission bits are not the model here")
        path = os.path.join(self.dir, "policy.json")
        hostos.write_json_atomic(path, {"a": 1})
        for mode in (0o640, 0o604, 0o660, 0o666):
            os.chmod(path, mode)
            hostos.write_json_atomic(path, {"a": mode})
            self.assertEqual(
                mode, os.stat(path).st_mode & 0o777,
                "an atomic write changed permissions the user chose - the "
                "repair is reaching past the one mode it is meant to know")


class PrefsSurvivesADamagedOrUnwritableFileTest(unittest.TestCase):
    """settings.json is read at panel construction and written from
    ordinary sidebar use, so both directions have to fail softly."""

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
        """load()'s own docstring promises an exception here would kill
        the panel during construction with no interface and no message -
        and every key is read with a default for that reason. A top
        level that is not an object has no .get() at all."""
        self._write('["not", "an", "object"]')
        p = self._prefs()
        self.assertFalse(p.load(), "a wrong-shaped file loaded as usable")
        self.assertTrue(getattr(p, "_load_failed", False),
                        "the write latch was not set, so the next save "
                        "would overwrite the file with defaults")

    def test_a_top_level_string_does_not_kill_the_panel(self):
        self._write('"just a string"')
        p = self._prefs()
        self.assertFalse(p.load())
        self.assertTrue(getattr(p, "_load_failed", False))

    def test_a_normal_settings_file_still_loads(self):
        """So the guard cannot be satisfied by refusing everything."""
        self._write(json.dumps({"directory": "", "img_dir": "img/"}))
        p = self._prefs()
        p.load()
        self.assertFalse(getattr(p, "_load_failed", False),
                         "an ordinary settings file was treated as damaged")

    def test_a_failed_write_is_recorded_and_does_not_raise(self):
        """The only atomic writer in the package that reported nothing
        on failure, with none of its callers wrapping it - so a full
        disk lost every preference change in silence."""
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
            log.matching("settings.json could not be written", "prefs"),
            "a failed settings write left no trace at all")


class NoContentWriterTargetsItsDestinationTest(unittest.TestCase):
    """A SOURCE-derived scan, because the per-writer tests above are a
    LIST and a list is only as good as whoever remembered to extend it.

    prepare_cop_companion wrote its companion network straight onto the
    live destination for as long as it existed, and every behavioural
    test here stayed green throughout - they each drive one named
    writer, and that one was never named. This asserts the property
    across the whole package instead: a node archive is written to a
    SCRATCH and swapped in, never onto the path it is replacing.

    Asset content has no `.bak-*` tier - the databases get
    snapshot_before_write, `mat/` gets nothing - so a truncated write
    here is not a recoverable inconsistency, it is a material that no
    longer exists.
    """

    #: Names a scratch is allowed to arrive under. `scratch` is
    #: hostos.scratch_beside's yield; `path` is save_asset_pair's
    #: write_mat callback parameter, which is handed the scratch.
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
    """The .bak-* tiers live INSIDE the library, and the library lives
    in a synced folder - measured: the sync client tracks 15 in-library
    .bak paths, so the restore points sit inside the tree they exist to
    protect against, exactly as hostos's own docstring warns.

    The daily ledger is the answer to the failure the ring cannot cover:
    "this file was already wrong yesterday and the sync has since
    carried that everywhere". It is ADDED, not moved - the in-library
    tier is what lets a library be recovered on a machine that has never
    seen it before.
    """

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

    def test_the_entry_lands_outside_the_library(self):
        self._write({"assets": [{"id": "A"}]})
        entry = hostos.record_history(self.path)
        self.assertTrue(entry, "no history entry was written")
        self.assertFalse(
            os.path.abspath(entry).startswith(os.path.abspath(self.dir)),
            "the history entry is inside the library it protects - the "
            "same tree a sync client propagates corruption through")

    def test_the_content_round_trips(self):
        self._write({"assets": [{"id": "A", "name": "gold"}]})
        entry = hostos.record_history(self.path)
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
        """The same rule the .bak tier follows: recording garbage spends
        the day's slot while the good state ages out behind it."""
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
        """The name carries the date the copy is OF; mtime records when
        it was written, and a restore or a file copy rewrites that."""
        folder = hostos.history_root(self.path)
        os.makedirs(folder, exist_ok=True)
        made = []
        for day in range(1, 8):
            name = "library.json.2026-01-%02d.gz" % day
            full = os.path.join(folder, name)
            with gzip.open(full, "wb") as fh:
                fh.write(b"{}")
            made.append(name)
        # Touch the OLDEST so mtime and date disagree.
        os.utime(os.path.join(folder, made[0]), None)
        hostos._prune_history(folder, "library.json", days=3)
        left = sorted(n for n in os.listdir(folder) if n.endswith(".gz"))
        self.assertEqual(made[-3:], left,
                         "pruning kept the wrong entries - it is following "
                         "mtime, which a restore or a copy rewrites")

    def test_a_save_records_history_without_being_asked(self):
        """Wired into the one chokepoint every database already uses, so
        a new database cannot be added without history."""
        self._write({"assets": []})
        hostos.snapshot_before_write(self.path)
        self.assertEqual(1, len(self._entries()),
                         "snapshot_before_write did not record a history "
                         "entry, so nothing outside the synced tree holds "
                         "yesterday's state")


class TwoPanesEditSettingsWithoutClobberTest(unittest.TestCase):
    """panel.py constructs a Prefs per pane tab, so two writers of
    settings.json is ordinary use. There was no stale-write handling at
    all - gradients.json already had it - and either pane's save erased
    the other's whole document.
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_prefs_merge_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def _prefs(self):
        p = prefs.Prefs()
        p.path = self.dir
        p.load()
        return p

    def test_a_folder_added_by_the_other_pane_survives(self):
        pane_a = self._prefs()
        pane_a.save()                       # settings.json exists

        pane_b = self._prefs()              # reads the same file

        pane_a.add_file_folder("/theirs/textures")
        pane_a.save()

        pane_b.thumbsize = 256              # knows nothing of the folder
        pane_b.save()

        check = prefs.Prefs()
        check.path = self.dir
        check.load()
        self.assertIn("/theirs/textures",
                      [str(f) for f in check.file_folders],
                      "pane B's save erased the folder pane A had just "
                      "added - the whole document was clobbered")
        self.assertEqual(256, check.thumbsize,
                         "pane B's own change did not land")

    def test_the_adoption_SURVIVES_the_next_save_from_the_same_pane(self):
        """One save was the whole lifetime of the merge.

        The merge repaired `self.data`, but `save()` runs
        `refresh_data()` first and that rebuilds every collected key
        from the backing attributes - so the adopted entries were gone
        again on the next save from the same object, and by then
        `_disk_stat` matched the file this pane had just written, so
        the merge early-returned instead of re-adopting.

        The sibling test above saves once per pane and stayed green
        through all of it. Closing Preferences alone saves twice.
        """
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

    def test_a_location_LABEL_saved_by_the_other_pane_survives(self):
        """The four location decorations travel inside
        `file_location_records` since 2026-08-05, and `refresh_data`
        DERIVES the four old keys from those records. The merge's old
        dict arms adopted the derived keys into attributes refresh_data
        no longer reads - dead writes - so pane B's save put its stale
        records over pane A's fresh ones, and A's label was gone from
        the fallback copy (and from any store later seeded from it)."""
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
        """The merge adopts into ATTRIBUTES, so a collected key with no
        entry in _COLLECTED_ATTRS would raise KeyError mid-save - and a
        new list-valued preference is exactly the kind of thing that
        gets added to _LIST_KEYS alone.

        Asserted as an empty SET, not a count: "found none" and
        "everything is covered" have to be different answers.
        """
        collected = set(prefs.Prefs._LIST_KEYS) | set(prefs.Prefs._DICT_KEYS)
        mapped = set(prefs.Prefs._COLLECTED_ATTRS)
        self.assertEqual(
            set(), collected - mapped,
            "collected settings keys with no backing attribute mapped")
        self.assertEqual(
            set(), mapped - collected,
            "_COLLECTED_ATTRS names keys the merge never walks")
        blank = prefs.Prefs()
        for key, (attr, _is_path) in prefs.Prefs._COLLECTED_ATTRS.items():
            self.assertTrue(
                hasattr(blank, attr),
                "%s maps to %s, which a fresh Prefs does not have"
                % (key, attr))

    def test_a_scalar_takes_the_saving_pane(self):
        """The merge must not turn scalars into a fight: the pane the
        user is touching wins the single-choice keys."""
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
    """.bak-first is write-once forever - and the permanent floor being
    garbage is worse than no floor: a single half-synced launch minted
    it from a truncated file, and the rolling ring then aged every good
    state out behind it."""

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
        """The control: replacing a HEALTHY floor because it differs is
        the floor failing at its whole job."""
        with open(self.path + ".bak-first", "w", encoding="utf-8") as fh:
            json.dump({"assets": [{"id": "OLD-STATE"}]}, fh)
        hostos.snapshot_before_write(self.path)
        self.assertIn("OLD-STATE", self._floor(),
                      "a parseable .bak-first was overwritten - the "
                      "earliest state is gone")


class SnapshotsAreThrottledNotOncePerProcessTest(unittest.TestCase):
    """The once-per-session gate meant the rolling .bak-N ring captured
    at most ONE state per launch - a day of work in one session had a
    single restore point, and the ring mostly held air."""

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
            # Advance the clock past the threshold by backdating the
            # recorded stamp - monotonic time itself cannot be moved.
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
    """`library_user` is WHO this is. It keys everything stored per user
    in the library AND it signs versions - one field, because two fields
    is what forced the conflict that retired `version_author`: versions
    need the name to DIFFER per machine, favourites need it to MATCH
    across a user's machines, and one preference cannot do both
    (ROADMAP line 21).

    An auto-harvested name puts a real person's identity into a library
    that may be shared, without them choosing it (step 35) - that ban is
    unchanged and is the last test here.
    """

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

    def test_prefs_cannot_resolve_the_identity_itself(self):
        """THE SPLIT. Answering *who am I* can require MINTING a user
        into the library, and this file holds a pointer without knowing
        what it points at - the same way it holds `directory` without
        knowing what is in it. A resolver here would have to reach the
        library from inside the preferences object.
        """
        p = self._prefs_at(self._home())
        self.assertFalse(hasattr(p, "resolve_library_user"),
                         "prefs grew an identity resolver again - "
                         "minting belongs to core/users.py")
        self.assertFalse(hasattr(prefs, "DEFAULT_LIBRARY_USER"),
                         "a fixed default name is back; a library with "
                         "no users mints a colour name, and one WITH "
                         "users asks which of them this machine is")

    def test_an_existing_version_author_is_adopted(self):
        """The minted name BECOMES the user. Every `Plum-<n>` stem
        already on disk keeps matching its writer, and nothing is
        renamed - the other machine's name simply appears in the
        dropdown until its owner picks the one they want.
        """
        home = self._home()
        self._write_settings(home, {"version_author": "Plum"})
        self.assertEqual("Plum", self._prefs_at(home).library_user)

    def test_the_retired_author_key_is_dropped_on_save(self):
        """A key `_RETIRED_KEYS` does not name is carried back verbatim
        by the unknown-key courtesy on every save, so the field would
        outlive the code that read it - on every machine.
        """
        home = self._home()
        self._write_settings(home, {"version_author": "Plum"})
        p = self._prefs_at(home)
        p.save()
        with open(os.path.join(home, "settings.json"),
                  encoding="utf-8") as handle:
            stored = json.load(handle)
        self.assertNotIn("version_author", stored,
                         "the retired key survived a save")
        self.assertEqual("Plum", stored.get("library_user"))

    # Signing is `TheUserIsAUidWithANameTest` now: it needs a real
    # library, because resolving a UID to its name reads a store. A
    # copy here would have run with `dir` unset and written a
    # `users.json` into the working directory.

    def test_no_identity_source_touches_the_author_path(self):
        """Source-derived ban: machine_name, platform.node, getpass and
        $USER may never appear in the prefs PACKAGE - the identity is
        typed by a person, or it is the shipped default that is the same
        everywhere. Never the computer's account or machine name.

        WALKS EVERY MODULE, not the one that used to hold everything.
        `library_user` is answered in `prefs.py` but both saved and
        loaded in `persistence.py`, and `load()` is exactly where a
        default would be backfilled from the account name - it is also
        where the `version_author` adoption reads. Scanning a single
        module would have left that half uncovered - and would have kept
        PASSING while it did, which is how a guard becomes decoration.

        **AND IT NOW WALKS `core/users.py` TOO**, which is where naming
        a user actually happens since the identity became a UID. The
        minting moved out of this package on 2026-08-12 and the ban did
        not follow it for one commit - a guard pointed at the module the
        risk used to live in is the same decoration by another route.
        """
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
            # CODE only. The module's own comment names the banned
            # sources while explaining the ban - which is exactly what
            # a comment is for, and exactly what this scan must not
            # trip on (the same lesson as the credit-by-position pin
            # catching its own comment).
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
        # A walk that finds nothing passes silently: name what it must
        # have seen, so a rename cannot empty the ban.
        self.assertIn("prefs.py", checked)
        self.assertIn("persistence.py", checked)
        self.assertIn("users.py", checked)


class TheUserIsAUidWithANameTest(unittest.TestCase):
    """A user is a UID and a NAME beside it. Everything a user owns is
    tagged with the UID, never with the name they typed, so a rename
    relinks one label and moves no data at all.

    THE ASSET CONVENTION APPLIED TO PEOPLE. `material.py:164` mints a
    `uuid4` into `id` and keeps `name` separate, which is exactly why
    one favourites list is safe across libraries. A person is the same
    shape, and the alternative - keying on the typed name - reintroduces
    every problem ids were minted to remove.
    """

    def _prefs(self):
        from amaze.tests import test_support
        return test_support.fixture_prefs(self)

    def test_creating_a_user_answers_a_uid_not_the_name(self):
        from amaze.core import users
        p = self._prefs()
        uid = users.create(p, "Plum")
        self.assertTrue(uid)
        self.assertNotEqual("Plum", uid,
                            "the tag is the typed name - a rename would "
                            "then have to move every tagged row")
        self.assertEqual("Plum", users.name_for(p, uid))

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

    def test_two_users_may_share_a_name(self):
        """A name-keyed scheme cannot allow this; a UID-keyed one has
        nothing to collide."""
        from amaze.core import users
        p = self._prefs()
        first = users.create(p, "Plum")
        second = users.create(p, "Plum")
        self.assertNotEqual(first, second)
        self.assertEqual(2, len(users.all_users(p)))

    def test_the_current_user_is_a_uid_and_persists(self):
        from amaze.core import users
        p = self._prefs()
        uid = users.current(p)
        self.assertTrue(uid)
        self.assertEqual(uid, p.library_user,
                         "the machine-local pointer must hold the UID")
        self.assertEqual(uid, users.current(p),
                         "a second call minted a second identity")

    def test_a_name_left_by_the_first_build_is_adopted_onto_a_uid(self):
        """Step 1 shipped `library_user` holding a NAME. That install
        keeps its name and gains a UID for it - it does not become a
        second person, and its version stems still match."""
        from amaze.core import users
        p = self._prefs()
        p.library_user = "Plum"
        uid = users.current(p)
        self.assertNotEqual("Plum", uid)
        self.assertEqual("Plum", users.name_for(p, uid),
                         "the existing name was dropped instead of "
                         "carried onto the new UID")

    def test_a_library_with_no_users_mints_one_on_a_colour_name(self):
        """A brand-new library asks nobody anything. The colour mint is
        back after step 1 deleted it, with its unit changed: once per
        LIBRARY for its first user, never per machine."""
        from amaze.core import users
        p = self._prefs()
        # NOBODY, said out loud. The shared fixture POINTS at a user so
        # tagged stores can key; the mint only runs on an empty
        # pointer, and a carried one is ADOPTED AS A NAME - so leaving
        # it would name the first user after a UID.
        p.library_user = ""
        self.assertEqual(users.MINT, users.first_run_state(p))
        uid = users.current(p)
        self.assertIn(users.name_for(p, uid), users.PLACEHOLDER_NAMES)

    def test_an_existing_library_asks_instead_of_minting(self):
        """THE SECOND MACHINE. A library that already has users, met by
        a machine whose pointer names none of them, must ASK - pick an
        existing user or create one. Minting here silently turns one
        person into two, which is the whole failure this prevents."""
        from amaze.core import users
        p = self._prefs()
        users.create(p, "Plum")
        p.library_user = ""
        self.assertEqual(users.ASK, users.first_run_state(p))
        self.assertIsNone(users.current(p),
                          "it minted a second identity instead of "
                          "asking which user this is")

    def test_a_pointer_that_resolves_is_never_asked_again(self):
        from amaze.core import users
        p = self._prefs()
        uid = users.create(p, "Plum")
        p.library_user = uid
        self.assertEqual(users.RESOLVED, users.first_run_state(p))
        self.assertEqual(uid, users.current(p))

    def test_versions_sign_with_the_readable_name(self):
        """A stem of `a3f9c2e8-1.mat` is unreadable and would match no
        `Plum-<n>` already on disk. The UID identifies; the NAME signs.
        """
        from amaze.core import users, versions
        p = self._prefs()
        uid = users.create(p, "Plum")
        p.library_user = uid
        self.assertEqual("Plum", versions.writer_tag(p))


class TheSecondMachineIsAskedWhoItIsTest(unittest.TestCase):
    """A library with people in it, met by a machine that is none of
    them, ASKS instead of minting - the one case where the question is
    worth its cost, because minting there turns one person into two.
    """

    def _panel(self):
        from amaze.tests import test_support
        return test_support.fixture_panel(self)

    def test_it_adopts_an_existing_user_that_was_picked(self):
        from amaze.core import users
        panel = self._panel()
        uid = users.create(panel.prefs, "Cobalt")
        panel.prefs.library_user = ""
        picked = panel.ensure_library_user(lambda known: (uid, ""))
        self.assertEqual(uid, picked)
        self.assertEqual(uid, panel.prefs.library_user)
        self.assertEqual(1, len(users.all_users(panel.prefs)),
                         "picking an existing user minted another")

    def test_it_creates_when_a_new_name_was_given(self):
        from amaze.core import users
        panel = self._panel()
        users.create(panel.prefs, "Cobalt")
        panel.prefs.library_user = ""
        made = panel.ensure_library_user(lambda known: ("", "Sienna"))
        self.assertTrue(made)
        self.assertEqual("Sienna", users.name_for(panel.prefs, made))
        self.assertEqual(2, len(users.all_users(panel.prefs)))

    def test_a_cancel_leaves_no_user_and_asks_again(self):
        """Cancelling must not fall back to minting or to a blank key:
        nothing is keyed this session and the question returns."""
        from amaze.core import users
        panel = self._panel()
        users.create(panel.prefs, "Cobalt")
        panel.prefs.library_user = ""
        self.assertEqual("", panel.ensure_library_user(lambda k: ("", "")))
        self.assertEqual("", panel.prefs.library_user)
        self.assertEqual(users.ASK, users.first_run_state(panel.prefs))

    def test_a_resolved_machine_is_never_asked(self):
        from amaze.core import users
        panel = self._panel()
        uid = users.create(panel.prefs, "Cobalt")
        panel.prefs.library_user = uid

        def _refuse(known):
            raise AssertionError("asked a machine that already resolves")

        self.assertEqual(uid, panel.ensure_library_user(_refuse))

    def test_the_picker_offers_the_users_and_a_create_row(self):
        from amaze.dialogs import user_dialog
        dialog = user_dialog.UserPickerDialog(
            {"uid-a": "Cobalt", "uid-b": "Sienna"})
        self.addCleanup(dialog.deleteLater)
        combo = dialog._combo
        self.assertEqual(3, combo.count(), "users plus the create row")
        self.assertEqual(
            user_dialog.UserPickerDialog.CREATE,
            combo.itemData(combo.count() - 1),
            "the create row is not marked with the sentinel, so a "
            "library user named like it could be mistaken for it")


class AStoreCanTagItsKeysWithAnOwnerTest(unittest.TestCase):
    """A store may declare that its keys are TAGGED with the user, and
    the ENGINE does the tagging (ROADMAP line 21 step 2d).

    Asserted against a store this test builds itself, never against a
    shipped one. Two reasons, and both are the point of this commit:
    the mechanism is what is under test, so borrowing a section's store
    would measure that section too; and no shipped store sets the flag
    yet, so turning one on to test it is the change, not the test.

    Built with `Spec(...)` rather than `register(...)` DELIBERATELY -
    registering would put a fictional file in `stores()` and
    `filenames()`, which Repair surveys and the restore picker offers,
    for every test that runs after this one.
    """

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

    def test_two_users_do_not_see_each_others_entries(self):
        from amaze.core import keyed_store
        self.assertTrue(self._store("uid-one").set("~/a.exr", True))
        self.assertTrue(self._store("uid-one").has("~/a.exr"))
        keyed_store.release()
        self.assertFalse(
            self._store("uid-two").has("~/a.exr"),
            "the other user's entry is showing - the tag is not keeping "
            "them apart")
        keyed_store.release()
        self.assertTrue(self._store("uid-one").has("~/a.exr"),
                        "switching back lost the first user's entry")

    def test_the_stored_key_carries_the_uid(self):
        """On disk, so a store written by one build is readable by the
        next: `<uid>|<key>`, split on the FIRST separator only - a uuid4
        hex cannot contain one, a path can."""
        self._store("uid-one").set("~/a|b.exr", True)
        keys = list(self._on_disk())
        self.assertEqual(1, len(keys))
        tag, _sep, rest = keys[0].partition(self.SEP)
        self.assertEqual("uid-one", tag, "key %r is not tagged" % keys[0])
        self.assertEqual("~/a|b.exr", rest,
                         "a separator inside the KEY was eaten")

    def test_no_user_stores_nothing_rather_than_a_blank_bucket(self):
        """A machine that has not picked a user must not file entries
        under an empty tag: that bucket is not a shared user, it is an
        absent one."""
        from amaze.core import keyed_store
        written = self._store("").set("~/a.exr", True)
        self.assertFalse(written, "an entry was filed with no user")
        self.assertEqual(keyed_store.REASON_NO_USER, written.reason)
        self.assertFalse(self._store("").has("~/a.exr"))

    def test_all_is_scoped_and_everyones_is_not(self):
        """`all()` means the things that are MINE - it is what a section
        paints and what a sweep walks. `everyones()` is the unscoped
        read, for repair and migration, the only two jobs that
        legitimately see across people."""
        from amaze.core import keyed_store
        self._store("uid-one").set("~/mine.exr", True)
        keyed_store.release()
        self._store("uid-two").set("~/theirs.exr", True)
        keyed_store.release()
        store = self._store("uid-one")
        self.assertEqual(["~/mine.exr"], sorted(store.all()),
                         "all() is not scoped to this user")
        self.assertEqual(2, len(store.everyones()),
                         "everyones() cannot see across people")

    def test_a_row_from_before_the_store_had_owners_is_dropped(self):
        """A row written before the store had owners is REMOVED, not
        adopted - nothing on it says whose it was, so handing it to
        whoever opens the library first would give one person
        everybody's entries (ROADMAP line 21 step 2d).
        """
        self._plant("~/old.exr")
        store = self._store("uid-one")
        self.assertFalse(store.has("~/old.exr"),
                         "an entry from before the store had owners is "
                         "still showing")
        self.assertEqual({}, store.all())
        self.assertEqual({}, store.everyones(),
                         "the row was kept aside rather than dropped")

    def test_a_dropped_row_does_not_come_back_on_the_next_write(self):
        """The half `_foreign` would break: a value held aside as
        unreadable is written back on every save, so a pre-tag row must
        NOT be held there or the drop undoes itself."""
        self._plant("~/old.exr")
        self._store("uid-one").set("~/mine.exr", True)
        self.assertEqual(["uid-one" + self.SEP + "~/mine.exr"],
                         sorted(self._on_disk()),
                         "the untagged row was written back after being "
                         "dropped")

    def test_asking_for_nothing_is_not_a_refusal(self):
        """DOING NOTHING CANNOT FAIL. A store that can key nothing must
        still answer an empty write with UNCHANGED, or a caller that
        checks the answer reads a failure into an empty list - which is
        how `locations.migrate` came to refuse the LOCATIONS half, a
        store with no owner at all, on a machine with nobody picked.
        """
        from amaze.core import keyed_store
        store = self._store("")
        for written, what in ((store.update({}), "update"),
                              (store.rekey({}), "rekey"),
                              (store.retire([]), "retire")):
            self.assertTrue(written, "an empty %s was refused" % what)
            self.assertEqual(keyed_store.REASON_UNCHANGED, written.reason,
                             "an empty %s did not answer unchanged" % what)

    def test_an_untagged_store_is_completely_unaffected(self):
        """THE CONTROL, and the reason this can land before anything
        turns the flag on: with `user_tagged` false the engine must
        behave exactly as it did, including for a prefs carrying no
        user at all."""
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
    """The gate for 2026-08-05, when a probe wrote two files into the
    real synced library.

    The script MEANT to use a scratch library and set `dir` one line too
    late - after `load()`, which is where the location migration runs.
    Nothing caught it: the destructive-command hook reads shell commands
    for delete verbs, and this was a Python write. So the one function
    every JSON write goes through refuses on its own behalf when a run
    says it is only allowed to touch temporary files.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="amaze_sandbox_")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        # RESTORE WHAT WAS FOUND, never pop. Under the runner the
        # variable arrives armed for the WHOLE process, so a cleanup
        # that popped it disarmed every test that ran after this
        # module - and on 2026-08-13 a live settings load in that
        # unarmed tail wrote real favourites from inside a green
        # suite. The sentinel class at the bottom holds this.
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
        """Nothing in the product sets the variable, so the product must
        not be able to feel this. A guard that is on by accident in a
        live session would refuse the user's own saves."""
        os.environ.pop(hostos.SANDBOX_VAR, None)
        self.assertFalse(hostos.sandboxed())
        outside = os.path.join(self.tmp, "..", os.path.basename(self.tmp),
                               "unarmed.json")
        hostos.write_json_atomic(outside, {"a": 1})
        self.assertTrue(os.path.exists(outside))
        hostos.check_sandbox("/anywhere/at/all.json")

    def test_it_covers_a_keyed_store_and_the_databases_too(self):
        """The point of putting it in write_json_atomic rather than in
        one store: prefs, all four databases, the keyed stores and the
        manifests share that funnel, so one check covers every one of
        them and there is no per-caller list to be one short."""
        source = hostos.write_json_atomic.__doc__ or ""
        self.assertIn("front door", source)
        import inspect
        body = inspect.getsource(hostos.write_json_atomic)
        self.assertIn(
            "check_sandbox(path)", body,
            "the funnel no longer checks, so every caller is unguarded "
            "again")


class OnePathHasOneSpelling(unittest.TestCase):
    """A registered folder is written into settings.json by one encoder
    and into locations.json by another, and overview.md 4c says
    settings.json keeps a COPY of what those stores hold.

    Agreement held for a folder under home and broke for one BESIDE
    the install - where a Houdini user's textures naturally live.
    Measured 2026-08-10, this machine:

        settings.json   $AMAZE/../../SomeOther/textures
        locations.json  ~/Cloud/3D/H-FILES/SomeOther/textures

    The `..` walk breaks the moment the install moves; `~` survives it.
    Both decoders read both spellings, so one encoder wins and nothing
    needs migrating."""

    def _cases(self):
        from amaze.helpers import hostos
        amaze = os.environ.get("AMAZE", "")
        home = os.path.expanduser("~")
        cases = [os.path.join(home, "textures", "wood"),
                 home,
                 "/Volumes/Share/textures"]
        if amaze:
            # The divergent shape: shares a subtree with the install
            # without being under it.
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
        """Nothing migrates, so whatever is already in settings.json has
        to keep resolving - including the `$AMAZE/..` form this stops
        writing."""
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
        """`directory` is stored WITH one, and the connectors build
        their paths as `self._path + self._filename`."""
        from amaze.prefs import persistence
        for path in (os.path.expanduser("~") + "/Cloud/lib/",
                     "/Volumes/Share/lib/"):
            self.assertEqual(
                path, persistence._decode_path(
                    persistence._encode_path(path)),
                "the library pointer lost its trailing separator")


class TheSandboxStaysArmedForTheSuiteTest(unittest.TestCase):
    """The runner arms `AMAZE_SANDBOX` for the WHOLE process, and the
    sandbox tests above toggle it - so cleanup must put back the state
    setUp met, never pop the variable. A pop-as-cleanup left every
    test after this module running unarmed, and on 2026-08-13 a live
    settings load in that unarmed tail migrated real favourites into
    the real library from inside a green suite. Named after the guard
    class so it runs behind it in the loader's alphabetical order;
    standalone unarmed runs have nothing to hold and skip.
    """

    def test_the_armed_state_survived_the_sandbox_tests(self):
        if not _SANDBOX_ARMED_AT_IMPORT:
            self.skipTest("this process was never armed - run through "
                          "start_test.sh to hold the restoration")
        self.assertTrue(
            hostos.sandboxed(),
            "a sandbox test disarmed the process and never re-armed it "
            "- every test after this module can now write live data")


if __name__ == "__main__":
    unittest.main(verbosity=2)
