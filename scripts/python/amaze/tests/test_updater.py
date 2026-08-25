"""The updater, driven end to end with the single network door mocked - nothing here reaches GitHub, and the feed's real answers are reproduced as fixtures. ▸p/updater-shape ▸r/release-digest"""

import errno
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error

sys.path.insert(
    0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from amaze import branding                                # noqa: E402
from amaze.core import matx_sources, updater              # noqa: E402
from amaze.tests import test_support                      # noqa: E402,F401


class _Response(io.BytesIO):
    """What urlopen hands back, as a context manager with headers."""

    def __init__(self, payload, headers=None):
        super().__init__(payload if isinstance(payload, bytes)
                         else json.dumps(payload).encode("utf-8"))
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class _FeedMixin(unittest.TestCase):

    def answer(self, payload=None, headers=None, raising=None):
        """Point the ONE network door at a fixture."""
        calls = []

        def fake(url):
            calls.append(url)
            if raising is not None:
                raise raising
            return _Response(payload, headers)

        real = matx_sources._request
        matx_sources._request = fake
        self.addCleanup(setattr, matx_sources, "_request", real)
        return calls


class TheVersionComparisonTest(unittest.TestCase):

    def test_a_longer_version_is_newer_than_its_prefix(self):
        self.assertTrue(updater.is_newer("1.0.1", "1.0"))
        self.assertFalse(updater.is_newer("1.0", "1.0.1"))

    def test_the_leading_v_is_optional_on_either_side(self):
        """Measured in the wild: vscode tags `1.132.0`, node `v26.7.0`."""
        self.assertTrue(updater.is_newer("v2.0", "1.9"))
        self.assertFalse(updater.is_newer("v1.0", "1.0"))

    def test_the_same_version_is_not_newer(self):
        self.assertFalse(
            updater.is_newer(branding.APP_VERSION, branding.APP_VERSION))

    def test_ten_sorts_above_nine_rather_than_beside_it(self):
        self.assertTrue(updater.is_newer("1.10", "1.9"),
                        "versions compared as text put 1.10 below 1.9")

    def test_an_unreadable_piece_does_not_raise(self):
        updater.parts("v1.2.3-rc1+build")
        self.assertFalse(updater.is_newer("", "1.0"))


class TheCheckTest(_FeedMixin):

    def test_no_release_yet_is_reported_gracefully(self):
        """The ordinary answer until 1.0 is tagged: a measured 404 on a repo that itself answers 200. ▸p/updater-shape"""
        self.answer(raising=urllib.error.HTTPError(
            updater.RELEASES_URL, 404, "Not Found", {}, None))
        result = updater.check("1.0")
        self.assertEqual(updater.NO_RELEASE, result.verdict)
        self.assertFalse(result)
        self.assertIn("1.0", result.sentence)
        self.assertNotIn("error", result.sentence.lower(),
                         "no release yet is not a failure and must not "
                         "read like one")

    def test_a_newer_release_is_offered_with_its_download(self):
        self.answer({"tag_name": "v1.1",
                     "zipball_url": "https://example.invalid/z",
                     "assets": []})
        result = updater.check("1.0")
        self.assertEqual(updater.NEWER, result.verdict)
        self.assertTrue(result)
        self.assertEqual("v1.1", result.version)
        self.assertEqual("https://example.invalid/z", result.url)

    def test_a_release_with_no_assets_still_has_a_download(self):
        """Measured: `assets` is empty on plenty of real releases, so looking only there offers an update that cannot be fetched. ▸r/release-digest"""
        self.answer({"tag_name": "9.9", "assets": [],
                     "zipball_url": "https://example.invalid/src.zip"})
        self.assertTrue(updater.check("1.0").url,
                        "a source-only release came back with no URL")

    def test_an_uploaded_zip_wins_over_the_source_archive(self):
        self.answer({"tag_name": "9.9",
                     "zipball_url": "https://example.invalid/src",
                     "assets": [{"name": "amaze.zip",
                                 "browser_download_url":
                                 "https://example.invalid/built.zip"}]})
        self.assertEqual("https://example.invalid/built.zip",
                         updater.check("1.0").url)

    def test_the_same_version_reports_up_to_date(self):
        self.answer({"tag_name": "1.0", "assets": []})
        self.assertEqual(updater.UP_TO_DATE, updater.check("1.0").verdict)

    def test_an_unreachable_feed_changes_nothing_and_says_so(self):
        self.answer(raising=urllib.error.URLError("offline"))
        result = updater.check("1.0")
        self.assertEqual(updater.UNREACHABLE, result.verdict)
        self.assertIn("nothing has been changed", result.sentence.lower())

    def test_a_release_with_no_tag_cannot_be_compared(self):
        self.answer({"assets": []})
        self.assertEqual(updater.NO_RELEASE, updater.check("1.0").verdict)

    def test_the_check_asks_the_releases_endpoint_once(self):
        calls = self.answer({"tag_name": "1.0", "assets": []})
        updater.check("1.0")
        self.assertEqual([updater.RELEASES_URL], calls,
                         "the check must cost exactly one call - the "
                         "unauthenticated limit is 60 an hour")


class TheDownloadTest(_FeedMixin):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_update_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def test_a_complete_download_is_kept(self):
        self.answer(b"PK\x03\x04zipbody",
                    headers={"Content-Length": str(len(b"PK\x03\x04zipbody"))})
        path = updater.download("https://example.invalid/z", self.dir)
        self.assertTrue(os.path.exists(path))

    def test_a_truncated_download_is_refused_and_removed(self):
        """A short body ends the read loop NORMALLY, so without the length check a truncated archive is promoted as valid. ▸p/updater-shape"""
        self.answer(b"PK\x03\x04", headers={"Content-Length": "9999"})
        with self.assertRaises(OSError) as caught:
            updater.download("https://example.invalid/z", self.dir)
        self.assertIn("stopped early", str(caught.exception))
        self.assertEqual([], os.listdir(self.dir),
                         "the partial file was left behind")

    def test_an_empty_download_is_refused(self):
        self.answer(b"", headers={})
        with self.assertRaises(OSError):
            updater.download("https://example.invalid/z", self.dir)

    def test_a_missing_length_is_unknown_rather_than_zero(self):
        """Treating an absent Content-Length as 0 would refuse every server that does not send one. ▸p/updater-shape"""
        self.answer(b"PK\x03\x04body", headers={})
        self.assertTrue(
            os.path.exists(updater.download("https://x.invalid/z", self.dir)))

    def test_a_transfer_that_DIES_mid_read_leaves_nothing_behind(self):
        """The structural half the length check cannot cover: a transfer that RAISES reaches no check at all. ▸p/updater-shape"""
        class _Dying(_Response):
            def read(self, *args):
                if self.tell():
                    raise OSError("connection reset")
                return super().read(4)

        def fake(url):
            return _Dying(b"PK\x03\x04and then the wire drops",
                          {"Content-Length": "26"})

        real = matx_sources._request
        matx_sources._request = fake
        self.addCleanup(setattr, matx_sources, "_request", real)

        with self.assertRaises(OSError):
            updater.download("https://example.invalid/z", self.dir)
        self.assertEqual(
            [], os.listdir(self.dir),
            "a transfer that died mid-read left a truncated archive at "
            "the final path, where the next run reads it as a download "
            "that finished")


class TheSwapTest(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="amaze_swap_")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.install = os.path.join(self.root, "install")
        self.staged = os.path.join(self.root, "staged")
        for path, marker in ((self.install, "old"), (self.staged, "new")):
            os.makedirs(path)
            with open(os.path.join(path, "which.txt"), "w",
                      encoding="utf-8") as handle:
                handle.write(marker)

    def _which(self, path):
        with open(os.path.join(path, "which.txt"), encoding="utf-8") as fh:
            return fh.read()

    def test_the_new_install_takes_the_place_of_the_old(self):
        backup = updater.apply_update(self.staged, self.install)
        self.assertEqual("new", self._which(self.install))
        self.assertEqual("old", self._which(backup),
                         "the previous install must survive as .backup")

    def test_a_second_update_does_not_trip_on_the_old_backup(self):
        updater.apply_update(self.staged, self.install)
        os.makedirs(self.staged)
        with open(os.path.join(self.staged, "which.txt"), "w",
                  encoding="utf-8") as handle:
            handle.write("newer")
        updater.apply_update(self.staged, self.install)
        self.assertEqual("newer", self._which(self.install))

    def test_a_failed_swap_puts_the_old_install_back(self):
        """THE WINDOW between the two renames is the only moment there is no install, and nothing covered it. ▸p/updater-shape"""
        real = os.rename
        calls = []

        def failing(src, dst):
            calls.append(src)
            if len(calls) == 2:                  # the staged -> install move
                raise OSError("the second move failed")
            return real(src, dst)

        real_move = shutil.move

        def no_copy_either(src, dst):
            raise OSError("and the copy failed too")

        os.rename = failing
        shutil.move = no_copy_either
        self.addCleanup(setattr, shutil, "move", real_move)
        self.addCleanup(setattr, os, "rename", real)
        with self.assertRaises(OSError):
            updater.apply_update(self.staged, self.install)
        os.rename = real
        shutil.move = real_move
        self.assertTrue(
            os.path.isdir(self.install),
            "the install is GONE - the first move succeeded, the second "
            "failed, and nothing put it back")
        self.assertEqual("old", self._which(self.install))

    def test_a_cache_on_ANOTHER_VOLUME_still_installs(self):
        """`os.rename` raises EXDEV across a filesystem and only a copy crosses - the staged tree lives in the cache, which need not share a disk with the install. ▸r/cross-volume-move"""
        real = os.rename
        calls = []

        def cross_volume(src, dst):
            calls.append(src)
            if len(calls) == 2:                  # the staged -> install move
                raise OSError(errno.EXDEV, "Cross-device link")
            return real(src, dst)

        os.rename = cross_volume
        self.addCleanup(setattr, os, "rename", real)
        backup = updater.apply_update(self.staged, self.install)
        os.rename = real

        self.assertEqual(
            "new", self._which(self.install),
            "a cache on another volume left the update uninstalled")
        self.assertEqual("old", self._which(backup),
                         "the rollback copy was lost crossing the volume")

    def test_a_copy_that_dies_part_way_leaves_no_half_install(self):
        """Once the install has been renamed aside its path is free, so a copy that fails part way populates it with a fragment. ▸r/cross-volume-move"""
        real = os.rename
        real_move = shutil.move
        calls = []

        def cross_volume(src, dst):
            calls.append(src)
            if len(calls) == 2:
                raise OSError(errno.EXDEV, "Cross-device link")
            return real(src, dst)

        def half_a_copy(src, dst):
            os.makedirs(dst, exist_ok=True)
            with open(os.path.join(dst, "fragment.txt"), "w",
                      encoding="utf-8") as handle:
                handle.write("half")
            raise OSError("the volume filled up")

        os.rename = cross_volume
        shutil.move = half_a_copy
        self.addCleanup(setattr, shutil, "move", real_move)
        self.addCleanup(setattr, os, "rename", real)
        with self.assertRaises(OSError):
            updater.apply_update(self.staged, self.install)
        os.rename = real
        shutil.move = real_move

        self.assertEqual(
            "old", self._which(self.install),
            "the fragment was left where the install goes, so Houdini "
            "loads half a release")
        self.assertFalse(
            os.path.exists(os.path.join(self.install, "fragment.txt")),
            "the half-copied file survived the rollback")
        self.assertEqual("old", self._which(self.install))

    def test_a_missing_staged_update_leaves_the_install_alone(self):
        with self.assertRaises(OSError):
            updater.apply_update(os.path.join(self.root, "nothing"),
                                 self.install)
        self.assertEqual("old", self._which(self.install),
                         "the install was disturbed by an update that "
                         "was never there to apply")


class TheNetworkDoorTest(unittest.TestCase):

    def _source(self):
        path = os.path.join(os.path.dirname(os.path.abspath(updater.__file__)),
                            "updater.py")
        with open(path, encoding="utf-8") as handle:
            return handle.read()

    def test_the_updater_opens_no_url_of_its_own(self):
        """Scanned as a CALL, not as the word - naming the door in prose made the first version match itself. ▸p/updater-shape"""
        self.assertNotIn(
            "urlopen(", self._source(),
            "updater.py opens a URL directly, so the suite's block on "
            "matx_sources._request does not stop it and a test could "
            "reach GitHub")

    def test_the_feed_is_only_consulted_when_asked(self):
        """Nothing runs at import - a module-level call would check for updates on every panel open. ▸p/updater-shape"""
        source = self._source()
        module_level = [line for line in source.splitlines()
                        if line[:1].strip() and "check(" in line
                        and not line.startswith("def ")]
        self.assertEqual(
            [], module_level,
            "something calls check() at module level, so importing the "
            "package would reach the network: %s" % module_level)


class TheAboutTabCanActuallyRunAnInstall(unittest.TestCase):
    """The Qt slot no behaviour test reached, driven at the seam with the updater's two halves stubbed. ▸p/updater-shape"""

    def setUp(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6 import QtWidgets

        self.app = (QtWidgets.QApplication.instance()
                    or QtWidgets.QApplication([]))
        self.dir = tempfile.mkdtemp(prefix="amaze_update_ui_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def _dialog(self):
        from amaze.dialogs import prefs_dialog
        from amaze.tests import test_support

        prefs = test_support.fixture_prefs(self)
        dialog = prefs_dialog.PrefsDialog(prefs, panel=None)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_a_successful_install_reports_and_hides_the_button(self):
        import hou
        from unittest.mock import patch

        from amaze.core import updater

        install = os.path.join(self.dir, "install")
        os.makedirs(install)
        backup = os.path.join(self.dir, "install.backup")

        dialog = self._dialog()
        dialog._last_update = updater.Update(
            updater.NEWER, version="9.9",
            url="https://example.invalid/r.zip", sentence="newer")
        dialog._btn_install.setVisible(True)

        with patch.object(hou, "getenv", return_value=install), \
                patch.object(updater, "fetch_and_stage",
                             return_value=os.path.join(self.dir, "staged")), \
                patch.object(updater, "apply_update", return_value=backup):
            dialog.install_update()

        text = dialog._lbl_update.text()
        self.assertIn("9.9", text, "the sentence does not name the version")
        self.assertIn("Restart", text,
                      "nothing tells the user the new build is not live "
                      "until Houdini restarts")
        # isHidden(), never isVisible(): a QTabWidget page that is not current is explicitly hidden, so isVisible() answers False whatever the button was told ▸p/updater-shape
        self.assertTrue(dialog._btn_install.isHidden(),
                        "Install is still offered after installing")

    def test_a_refused_install_shows_the_updaters_own_sentence(self):
        import hou
        from unittest.mock import patch

        from amaze.core import updater

        install = os.path.join(self.dir, "install")
        os.makedirs(install, exist_ok=True)
        dialog = self._dialog()
        dialog._last_update = updater.Update(
            updater.NEWER, version="9.9",
            url="https://example.invalid/r.zip", sentence="newer")

        with patch.object(hou, "getenv", return_value=install), \
                patch.object(updater, "fetch_and_stage",
                             side_effect=OSError(
                                 "the downloaded file is not a zip "
                                 "archive. Nothing has been changed.")):
            dialog.install_update()

        self.assertIn("not a zip archive", dialog._lbl_update.text(),
                      "the updater's finished sentence was replaced or "
                      "swallowed")

    def test_an_unknown_install_location_changes_nothing(self):
        import hou
        from unittest.mock import patch

        from amaze.core import updater

        dialog = self._dialog()
        dialog._last_update = updater.Update(
            updater.NEWER, version="9.9",
            url="https://example.invalid/r.zip", sentence="newer")

        with patch.object(hou, "getenv", return_value=""), \
                patch.object(updater, "fetch_and_stage") as fetch:
            dialog.install_update()

        fetch.assert_not_called()
        self.assertIn("cannot tell where it is installed",
                      dialog._lbl_update.text())


class AReleaseIsStagedIntoTheINSTALLShape(unittest.TestCase):
    """The middle of the update, which shipped missing - a release zip is the whole repo and the install is four entries of it, so staging is a real step and not a rename. ▸p/updater-shape"""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_update_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def _release_zip(self, root="owner-repo-abc1234", extras=True,
                     omit=()):
        """A zip shaped like GitHub's zipball for a tag - `root` is a PREFIX, not a format slot, so an empty one must leave member names relative. ▸p/updater-shape"""
        import zipfile

        path = os.path.join(self.dir, "release.zip")
        prefix = (root + "/") if root else ""    # NOT `"%s/%s" %` - that writes `/scripts/...` for an empty root, an absolute path the containment check rightly refuses ▸p/updater-shape
        with zipfile.ZipFile(path, "w") as bundle:
            for entry in updater.INSTALL_ENTRIES:
                if entry in omit:
                    continue
                if entry.endswith(".xml"):
                    bundle.writestr(prefix + entry, "<menu/>")
                else:
                    bundle.writestr(prefix + entry + "/marker.txt",
                                    "from the release")
            if extras:
                bundle.writestr(prefix + "LICENSE", "GPLv3")
                bundle.writestr(prefix + "docs/architecture/overview.md", "#")
                bundle.writestr(prefix + "tools/sync-install.sh", "#!/bin/bash")
        return path

    def test_the_staged_tree_is_the_install_not_the_repo(self):
        staged = updater.stage_release(self._release_zip(),
                                       os.path.join(self.dir, "staged"))
        self.assertEqual(sorted(updater.INSTALL_ENTRIES),
                         sorted(os.listdir(staged)),
                         "the staged tree is not what the install holds")
        self.assertTrue(
            os.path.exists(os.path.join(staged, "scripts", "marker.txt")),
            "the staged tree did not carry the release's own files")

    def test_a_release_missing_an_install_entry_is_refused(self):
        with self.assertRaises(OSError) as caught:
            updater.stage_release(
                self._release_zip(omit=("toolbar",)),
                os.path.join(self.dir, "staged"))
        self.assertIn("toolbar", str(caught.exception))
        self.assertIn("Nothing has been changed", str(caught.exception))

    def test_a_member_that_escapes_the_staging_folder_is_refused(self):
        """The archive comes from a URL the release feed named, so a member called `../../x` writes wherever it points. ▸p/updater-shape"""
        import zipfile

        path = os.path.join(self.dir, "evil.zip")
        with zipfile.ZipFile(path, "w") as bundle:
            bundle.writestr("../../escaped.txt", "outside")
        with self.assertRaises(OSError) as caught:
            updater.stage_release(path, os.path.join(self.dir, "staged"))
        self.assertIn("outside the update folder", str(caught.exception))
        self.assertFalse(
            os.path.exists(os.path.join(self.dir, "escaped.txt")),
            "the escaping member was written before the refusal")

    def test_a_file_that_is_not_a_zip_is_refused_with_a_sentence(self):
        path = os.path.join(self.dir, "captive-portal.zip")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("<html>sign in to the wifi</html>")
        with self.assertRaises(OSError) as caught:
            updater.stage_release(path, os.path.join(self.dir, "staged"))
        self.assertIn("not a zip archive", str(caught.exception))

    def test_a_flat_archive_works_too(self):
        """An uploaded release asset need not wrap itself in a folder; only GitHub's generated zipball does. ▸p/updater-shape"""
        staged = updater.stage_release(
            self._release_zip(root="", extras=False),
            os.path.join(self.dir, "staged"))
        self.assertEqual(sorted(updater.INSTALL_ENTRIES),
                         sorted(os.listdir(staged)))

    def test_the_staged_tree_swaps_in_and_the_old_one_is_kept(self):
        """End to end, which is the thing that had never run."""
        install = os.path.join(self.dir, "install")
        os.makedirs(os.path.join(install, "scripts"))
        with open(os.path.join(install, "scripts", "old.txt"), "w",
                  encoding="utf-8") as handle:
            handle.write("the version being replaced")

        staged = updater.stage_release(self._release_zip(),
                                       os.path.join(self.dir, "staged"))
        backup = updater.apply_update(staged, install)

        self.assertTrue(
            os.path.exists(os.path.join(install, "scripts", "marker.txt")),
            "the release did not land in the install")
        self.assertTrue(
            os.path.exists(os.path.join(backup, "scripts", "old.txt")),
            "the previous install was not kept, so a bad release cannot "
            "be undone")

    def test_the_install_entries_match_the_ship_script(self):
        """Two homes for one list, so a source-derived guard rather than a promise. ▸p/updater-shape"""
        root = os.path.dirname(os.path.dirname(os.path.dirname(    # five dirnames to the repo root, the spelling test_keyed_store already uses
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
        script = os.path.join(root, "tools", "sync-install.sh")
        with open(script, encoding="utf-8") as handle:
            text = handle.read()
        for entry in updater.INSTALL_ENTRIES:
            self.assertIn(
                '"$install/%s"' % entry, text,
                "%s is staged by the updater and not placed by "
                "sync-install.sh - the two disagree about what an "
                "install is" % entry)


class AReleaseIsCheckedBeforeItIsTrusted(_FeedMixin):
    """What arrives over the wire is a file a remote catalogue named, and it is about to REPLACE the running install. ▸r/release-digest"""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="amaze_verify_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.body = b"PK\x03\x04a release"
        self.digest = "sha256:" + hashlib.sha256(self.body).hexdigest()

    def test_the_feed_s_digest_and_size_reach_the_caller(self):
        self.answer({
            "tag_name": "2.0",
            "assets": [{"name": "amaze.zip",
                        "browser_download_url": "https://x.invalid/a.zip",
                        "digest": self.digest, "size": len(self.body)}],
            "zipball_url": "https://x.invalid/src.zip"})
        result = updater.check("1.0")
        self.assertEqual(self.digest, result.digest)
        self.assertEqual(len(self.body), result.size)

    def test_the_generated_zipball_carries_no_digest(self):
        """GitHub publishes none for the archive it generates, so this path is honestly unverified rather than falsely reassuring."""
        self.answer({"tag_name": "2.0", "assets": [],
                     "zipball_url": "https://x.invalid/src.zip"})
        result = updater.check("1.0")
        self.assertEqual("https://x.invalid/src.zip", result.url)
        self.assertEqual("", result.digest)
        self.assertEqual(0, result.size)

    def test_a_matching_digest_is_kept(self):
        self.answer(self.body,
                    headers={"Content-Length": str(len(self.body))})
        path = updater.download("https://x.invalid/z", self.dir,
                                digest=self.digest, size=len(self.body))
        self.assertTrue(os.path.exists(path))

    def test_a_SUBSTITUTED_file_of_the_right_length_is_refused(self):
        """The length check cannot see this one: the bytes are a different file of exactly the declared size."""
        swapped = b"PK\x03\x04" + b"X" * (len(self.body) - 4)
        self.assertEqual(len(self.body), len(swapped))
        self.assertNotEqual(self.body, swapped)
        self.answer(swapped, headers={"Content-Length": str(len(swapped))})
        with self.assertRaises(OSError) as caught:
            updater.download("https://x.invalid/z", self.dir,
                             digest=self.digest, size=len(swapped))
        self.assertIn("checksum", str(caught.exception))
        self.assertEqual([], os.listdir(self.dir),
                         "the unverified file was promoted anyway")

    def test_a_checksum_this_amaze_cannot_compute_is_a_refusal(self):
        """"Cannot check" must never read as "checked"."""
        self.answer(self.body,
                    headers={"Content-Length": str(len(self.body))})
        with self.assertRaises(OSError) as caught:
            updater.download("https://x.invalid/z", self.dir,
                             digest="sha3-quantum:00ff")
        self.assertIn("cannot compute", str(caught.exception))

    def test_a_body_that_never_ends_is_cut_at_the_ceiling(self):
        """Without the ceiling this writes until the disk is full - the read loop's only other exit is the server choosing to stop."""
        class _Endless(_Response):
            def read(self, *args):
                return b"\0" * 65536

        real = matx_sources._request
        matx_sources._request = lambda url: _Endless(b"", {})
        self.addCleanup(setattr, matx_sources, "_request", real)

        with self.assertRaises(OSError) as caught:
            updater.download("https://x.invalid/z", self.dir)
        self.assertIn("larger than a release should be",
                      str(caught.exception))
        self.assertEqual([], os.listdir(self.dir))

    def test_the_declared_size_tightens_the_ceiling(self):
        """A release saying 10 bytes and sending megabytes is stopped at 10, not at the global ceiling."""
        class _Endless(_Response):
            def read(self, *args):
                return b"\0" * 65536

        real = matx_sources._request
        matx_sources._request = lambda url: _Endless(b"", {})
        self.addCleanup(setattr, matx_sources, "_request", real)

        with self.assertRaises(OSError) as caught:
            updater.download("https://x.invalid/z", self.dir, size=10)
        self.assertIn("over 10 bytes", str(caught.exception))

    def test_an_archive_that_unpacks_to_gigabytes_is_refused(self):
        """A zip bomb is small on the wire and enormous on disk, so only the header's declared expanded size sees it coming."""
        import zipfile
        archive = os.path.join(self.dir, "bomb.zip")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("scripts/big", b"\0" * (1024 * 1024))
        on_disk = os.path.getsize(archive)

        real_max = updater.MAX_UNPACKED_BYTES
        updater.MAX_UNPACKED_BYTES = 1024
        self.addCleanup(setattr, updater, "MAX_UNPACKED_BYTES", real_max)

        with self.assertRaises(OSError) as caught:
            updater.stage_release(archive, os.path.join(self.dir, "staged"))
        self.assertIn("unpacks to more than", str(caught.exception))
        self.assertLess(on_disk, 1024 * 1024,
                        "the fixture did not compress, so it does not "
                        "stand for a bomb")

    def test_an_ordinary_release_is_nowhere_near_the_ceilings(self):
        """The ceilings are guards, not a budget the real release lives inside - 41MB tracked today against 256/512MB."""
        self.assertGreater(updater.MAX_DOWNLOAD_BYTES, 200 * 1024 * 1024)
        self.assertGreaterEqual(updater.MAX_UNPACKED_BYTES,
                                updater.MAX_DOWNLOAD_BYTES)


if __name__ == "__main__":
    unittest.main()
